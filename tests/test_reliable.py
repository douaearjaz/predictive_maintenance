import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from src.io_utils import read_json, write_json
from src.reliable.sections import clean_with_map, evidence_span, parse_pdf
from src.reliable.pipeline import extract, candidates, inspect, review, validate
from src.reliable.fmea import build
from src.reliable.evaluate import evaluate, template


def statement(subject="voltage imbalance", target="excessive current", subject_kind="phenomenon", target_kind="phenomenon"):
    return {"subject": {"text": subject, "kind": subject_kind}, "relation": "CAUSES",
            "object": {"text": target, "kind": target_kind}, "qualifier": "can", "operating_conditions": None,
            "evidence": [{"paragraph_id": "p1", "quote": "Voltage imbalance can cause excessive current."}],
            "needs_context_review": False, "review_note": ""}


class ReliableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        original = "Voltage imbalance can cause excessive current.\nExcessive current can cause insulation breakdown."
        cleaned, mapping = clean_with_map(original)
        self.section = {"document_id": "DOC_fixture", "document_name": "fixture.pdf", "section_id": "fault-01",
                        "section": "Voltage imbalance", "pages": [1], "issues": [],
                        "paragraphs": [{"paragraph_id": "p1", "page": 1, "original_text": original,
                                        "cleaned_text": cleaned, "clean_to_original": mapping, "bbox": [0, 0, 100, 100], "issues": []}]}
        self.batch = self.root / "batch.json"
        self.batch_data = {"batch_id": "fixture", "parser_version": "fixture", "segmentation_version": "fixture",
                           "cleaning_version": "fixture", "pymupdf_version": "fixture", "sections": [self.section]}
        write_json(self.batch, self.batch_data)
        self.a = statement()
        self.b = statement("excessive current", "insulation breakdown", target_kind="failure_mode")
        self.b["evidence"][0]["quote"] = "Excessive current can cause insulation breakdown."
        self.response = {"content": json.dumps({"statements": [self.a, self.b], "mentions": [], "ambiguities": []}), "finish_reason": "stop"}
        self.mock = Mock(return_value=self.response)

    def run_extract(self, **kwargs):
        return extract(self.batch, self.root / "runs", complete=kwargs.pop("complete", self.mock), source_kind="test_fixture", **kwargs)

    def test_whitespace_mapping_is_lossless_and_keeps_hyphens(self):
        original = "  insu-\n lation\t  10 µA\n"
        cleaned, mapping = clean_with_map(original)
        self.assertEqual(cleaned, "insu- lation 10 µA")
        s = copy.deepcopy(self.section)
        s["paragraphs"][0].update(original_text=original, cleaned_text=cleaned, clean_to_original=mapping)
        ev = evidence_span({"paragraph_id": "p1", "quote": "lation 10 µA"}, s)
        self.assertEqual(ev["original_quote"], "lation\t  10 µA")
        self.assertEqual(original[ev["original_start"]:ev["original_end"]], ev["original_quote"])

    def test_real_pdf_has_complete_sections_and_no_diagram_mix(self):
        path, batch = parse_pdf("data/documents/trusted/13-common-causes.pdf", self.root / "sections")
        self.assertEqual(len(batch["sections"]), 15)
        for section in batch["sections"]:
            for p in section["paragraphs"]:
                clean, mapping = clean_with_map(p["original_text"])
                self.assertEqual((clean, mapping), (p["cleaned_text"], p["clean_to_original"]))
            if section["section_id"].startswith("fault"):
                self.assertIn("Instrument to measure and diagnose:", section["cleaned_text"])
                self.assertTrue(section["paragraphs"][0]["cleaned_text"].startswith(str(int(section["section_id"][-2:])) + " "))
        text = next(s["cleaned_text"] for s in batch["sections"] if s["section_id"] == "fault-02")
        self.assertIn("excessive current", text)
        self.assertIn("operating temperatures", text)
        self.assertNotIn("L3", text)
        self.assertEqual(parse_pdf("data/documents/trusted/13-common-causes.pdf", self.root / "sections")[0], path)

    def test_invalid_sibling_and_injected_review_flags(self):
        bad = copy.deepcopy(self.a)
        bad["evidence"][0]["quote"] = "imaginary quotation"
        injected = {**self.a, "semantic_review_status": "accepted"}
        raw = {"content": json.dumps({"statements": [bad, self.a, injected], "mentions": [], "ambiguities": []}), "finish_reason": "stop"}
        result = validate(raw, self.section, "test")["candidates"]
        self.assertEqual([c["evidence_valid"] for c in result], [False, True, False])
        self.assertTrue(all(c["semantic_review_status"] == "pending" for c in result))

    def test_foreign_paragraph_and_ambiguous_quote_rejected(self):
        with self.assertRaises(ValueError):
            evidence_span({"paragraph_id": "foreign", "quote": "current"}, self.section)
        with self.assertRaises(ValueError):
            evidence_span({"paragraph_id": "p1", "quote": "can cause"}, self.section)

    def test_resume_and_config_identity(self):
        run = self.run_extract(model="one")
        manifest = (run / "manifest.json").read_bytes()
        self.assertEqual(run, self.run_extract(model="one"))
        self.assertEqual(self.mock.call_count, 1)
        self.assertEqual((run / "manifest.json").read_bytes(), manifest)
        self.assertNotEqual(run, self.run_extract(model="two"))

    def test_partial_resume_and_no_retry_of_malformed_response(self):
        other = copy.deepcopy(self.section)
        other["section_id"] = "fault-02"
        self.batch_data["sections"].append(other)
        write_json(self.batch, self.batch_data)
        fail = Mock(side_effect=[self.response, RuntimeError("quota")])
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            self.run_extract(complete=fail)
        run = self.run_extract(complete=Mock(return_value={"content": "broken", "finish_reason": "stop"}))
        self.assertEqual(inspect(run)["responses"], 2)
        again = Mock()
        self.run_extract(complete=again)
        again.assert_not_called()
        self.assertTrue(inspect(run)["results"][1]["issues"])

    def test_review_gate_and_no_transitive_fmea(self):
        run = self.run_extract()
        self.assertEqual(build(run)[1]["records"], [])
        for c in candidates(run):
            review(run, c["candidate_id"], "accepted", "fixture reviewer", "Checked direct causal step", "assistant")
        self.assertEqual(build(run)[1]["records"], [])
        rows = build(run, allow_assistant=True)[1]["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cause"][0]["value"], "excessive current")
        self.assertNotIn("voltage imbalance", json.dumps(rows))
        for k in ["component", "function", "effect", "severity", "occurrence", "detection_rating", "rpn"]:
            self.assertIsNone(rows[0][k])
        self.assertEqual(rows[0]["status"], "assistant_verified_draft")

    def test_review_tamper_and_duplicate_rejected(self):
        self.response["content"] = json.dumps({"statements": [self.b, self.b], "mentions": [], "ambiguities": []})
        run = self.run_extract()
        first, second = candidates(run)
        with self.assertRaises(ValueError):
            review(run, second["candidate_id"], "accepted", "test", "duplicate")
        review(run, first["candidate_id"], "accepted", "test", "checked")
        path = next((run / "raw").glob("*.json"))
        raw = read_json(path)
        content = json.loads(raw["content"])
        content["statements"][0]["qualifier"] = "asserted"
        raw["content"] = json.dumps(content)
        write_json(path, raw)
        with self.assertRaisesRegex(ValueError, "changed after review"):
            build(run)

    def test_mentions_and_ambiguities_cannot_make_rows(self):
        self.response["content"] = json.dumps({"statements": [], "mentions": [{"concept": self.b["object"], "evidence": self.b["evidence"]}],
                                              "ambiguities": [{"description": "unclear association", "evidence": self.b["evidence"]}]})
        run = self.run_extract()
        for c in candidates(run):
            review(run, c["candidate_id"], "accepted", "test", "checked mention only")
        self.assertEqual(build(run)[1]["records"], [])

    def test_evaluation_missing_unsupported_role_and_qualifier(self):
        wrong = copy.deepcopy(self.a)
        wrong["relation"] = "ASSOCIATED_WITH"
        collapsed = statement("voltage imbalance", "insulation breakdown", target_kind="failure_mode")
        modal = copy.deepcopy(self.b)
        modal["qualifier"] = "asserted"
        self.response["content"] = json.dumps({"statements": [wrong, collapsed, modal], "mentions": [], "ambiguities": []})
        run = self.run_extract()
        ref = template(self.batch_data)
        ref["review_status"] = "assistant_draft"
        ref["sections"][0].update(review_status="assistant_draft", expected_relations=[self.a, self.b], forbidden_relations=[collapsed])
        path = self.root / "reference.json"
        write_json(path, ref)
        _, report = evaluate(run, path)
        self.assertEqual(report["totals"]["correct_relations"], 0)
        self.assertEqual(report["totals"]["missing_relations"], 2)
        self.assertEqual(report["totals"]["unsupported_facts"], 1)
        self.assertEqual(report["totals"]["wrong_role_or_association"], 2)
        self.assertEqual(report["totals"]["qualifier_or_condition_errors"], 1)


    def test_conditions_need_their_own_exact_evidence(self):
        item = copy.deepcopy(self.a)
        item["operating_conditions"] = {"text": "above 100 degrees", "evidence": [{"paragraph_id": "p1", "quote": "above 100 degrees"}]}
        raw = {"content": json.dumps({"statements": [item], "mentions": [], "ambiguities": []}), "finish_reason": "stop"}
        result = validate(raw, self.section, "condition")["candidates"][0]
        self.assertTrue(result["schema_valid"])
        self.assertFalse(result["evidence_valid"])

    def test_aliases_preserve_roles_and_modality(self):
        run = self.run_extract()
        ref = template(self.batch_data)
        expected = copy.deepcopy(self.a)
        expected["subject"]["text"] = "imbalance"
        expected["relation"] = "LEADS_TO"
        expected["qualifier"] = "can cause"
        ref["relation_aliases"] = {"LEADS_TO": "CAUSES"}
        ref["qualifier_aliases"] = {"can cause": "can"}
        ref["sections"][0].update(review_status="assistant_draft", aliases={"imbalance": "voltage imbalance"}, expected_relations=[expected])
        path = self.root / "reference.json"
        write_json(path, ref)
        self.assertEqual(evaluate(run, path)[1]["totals"]["correct_relations"], 1)
        expected["subject"]["kind"] = "component"
        write_json(path, ref)
        report = evaluate(run, path)[1]
        self.assertEqual(report["totals"]["correct_relations"], 0)
        self.assertEqual(report["totals"]["wrong_role_or_association"], 1)

    def test_truncation_is_preserved_and_never_accepted(self):
        raw = {"content": self.response["content"], "finish_reason": "length"}
        run = self.run_extract(complete=Mock(return_value=raw))
        self.assertEqual(candidates(run), [])
        self.assertTrue(inspect(run)["results"][0]["issues"])
        self.assertEqual(build(run, True)[1]["records"], [])


if __name__ == "__main__":
    unittest.main()
