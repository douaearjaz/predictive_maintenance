import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import fitz
from pydantic import ValidationError
from src.ingestion.chunker import chunk_page
from src.ingestion.pdf_parser import parse_directory
from src.extraction.schemas import FIELDS, TechnicalRecord, ReviewDecision
from src.extraction.extractor import extract_batch, refresh_index, validate_response, groq_completion
from src.validation.validator import validate_record
from src.validation.normalizer import normalize_record
from src.validation.review import record_decision
from src.fmea.fmea_builder import build_fmea
from src.causal.relation_builder import build_relations
from src.io_utils import read_json, write_json

PASSAGE = (Path(__file__).parent / "fixtures/motor_fault.txt").read_text().strip()


def example(chunk):
    def evidence(quote):
        return {k: getattr(chunk, k) for k in ("document_id", "document_name", "page", "chunk_id")} | {"quote": quote}
    first, second = PASSAGE.split(". ", 1)
    first += "."
    record = dict.fromkeys(FIELDS)
    for name, value, quote in [("cause", "Insufficient lubrication", first),
                               ("failure_mode", "accelerated bearing wear", first),
                               ("symptom", "excessive vibration", second),
                               ("detection_method", "vibration monitoring", second)]:
        record[name] = {"value": value, "evidence": [evidence(quote)]}
    record["relations"] = [
        {"source": "Insufficient lubrication", "relation_type": "CAUSES", "target": "accelerated bearing wear",
         "evidence": [evidence(first)], "operating_conditions": None},
        {"source": "accelerated bearing wear", "relation_type": "RESULTS_IN", "target": "excessive vibration",
         "evidence": [evidence(second)], "operating_conditions": None},
        {"source": "excessive vibration", "relation_type": "DETECTED_BY", "target": "vibration monitoring",
         "evidence": [evidence(second)], "operating_conditions": None},
    ]
    return record


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.chunk = chunk_page(PASSAGE, "DOC_fixture", "motor_fault.pdf", 1)[0]
        self.batch = self.root / "chunks.json"
        write_json(self.batch, {"chunks": [self.chunk.model_dump()]})
        self.mock = Mock(side_effect=lambda c, m: {"content": json.dumps({"records": [example(c)]}), "finish_reason": "stop"})

    def run_extraction(self, complete=None, **kwargs):
        return extract_batch(self.batch, self.root / "candidates", complete=complete or self.mock, **kwargs)

    def test_full_review_export_and_resume(self):
        run = self.run_extraction()
        self.run_extraction()
        self.assertEqual(self.mock.call_count, 1)
        folder, records = build_fmea(run, self.root / "reviewed", self.root / "fmea")
        self.assertEqual(records, [])
        candidate = refresh_index(run)[0]
        record_decision(run, self.root / "reviewed", ReviewDecision(candidate_id=candidate["candidate_id"],
                        decision="approved", reviewer="unit-test", note="Checked fixture quotations and semantics"))
        folder, records = build_fmea(run, self.root / "reviewed", self.root / "fmea")
        self.assertEqual(len(records), 1)
        for field in ["component", "function", "effect", "maintenance_action", "severity", "occurrence", "detection_rating", "rpn"]:
            self.assertIsNone(records[0][field])
        self.assertIn("cause_evidence", (folder / "fmea.csv").read_text())
        relations = build_relations(records, self.root / "relations.json")
        self.assertEqual(len(relations), 3)
        self.assertEqual(relations[0]["review_status"], "pending")
        self.assertEqual(relations[0]["linked_fmea_record_id"], records[0]["fmea_record_id"])

    def test_reject_fabricated_quote_and_wrong_page(self):
        record = example(self.chunk)
        record["cause"]["evidence"][0]["quote"] = "invented support"
        record["failure_mode"]["evidence"][0]["page"] = 9
        errors = validate_record(TechnicalRecord.model_validate(record), {self.chunk.chunk_id: self.chunk})
        self.assertTrue(any("quotation" in e for e in errors))
        self.assertTrue(any("provenance" in e for e in errors))

    def test_missing_provenance_empty_fields_and_invalid_relation(self):
        for modification in ["missing", "empty", "relation"]:
            record = example(self.chunk)
            if modification == "missing":
                del record["cause"]["evidence"][0]["chunk_id"]
            elif modification == "empty":
                record["cause"]["value"] = "   "
            else:
                record["relations"][0]["relation_type"] = "AND"
            with self.assertRaises(ValidationError):
                TechnicalRecord.model_validate(record)

    def test_relation_endpoints_must_match_fields(self):
        record = example(self.chunk)
        record["relations"][0]["target"] = "motor explosion"
        self.assertTrue(validate_record(TechnicalRecord.model_validate(record), {self.chunk.chunk_id: self.chunk}))

    def test_preserve_malformed_and_truncated_responses_without_resending(self):
        for content, reason in [("not json", "stop"), ('{"records": []}', "length")]:
            mock = Mock(return_value={"content": content, "finish_reason": reason})
            run = self.run_extraction(mock, model=reason)
            self.run_extraction(mock, model=reason)
            self.assertEqual(mock.call_count, 1)
            self.assertTrue(read_json(run / "index.json")["issues"])
            self.assertEqual(read_json(next((run / "raw").glob("*.json")))["content"], content)

    def test_invalid_candidate_is_preserved_and_cannot_be_approved(self):
        bad = example(self.chunk)
        bad["cause"]["evidence"][0]["quote"] = "not in source"
        run = self.run_extraction(Mock(return_value={"content": json.dumps({"records": [bad]}), "finish_reason": "stop"}))
        candidate = refresh_index(run)[0]
        self.assertEqual(candidate["raw_record"], bad)
        with self.assertRaises(ValueError):
            record_decision(run, self.root / "reviewed", ReviewDecision(candidate_id=candidate["candidate_id"], decision="approved", reviewer="test", note="test"))

    def test_rate_limit_resume_keeps_prior_response(self):
        other = chunk_page(PASSAGE, "DOC_fixture", "motor_fault.pdf", 2)[0]
        write_json(self.batch, {"chunks": [self.chunk.model_dump(), other.model_dump()]})
        calls = []
        def interrupt(chunk, model):
            calls.append(chunk.chunk_id)
            if len(calls) == 2:
                raise RuntimeError("simulated token limit")
            return self.mock(chunk, model)
        with self.assertRaises(RuntimeError):
            self.run_extraction(interrupt)
        self.run_extraction()
        self.assertEqual(self.mock.call_count, 2)
        self.assertEqual(self.mock.call_args[0][0].page, 2)

    def test_duplicate_records_preserved(self):
        record = example(self.chunk)
        mock = Mock(return_value={"content": json.dumps({"records": [record, record]}), "finish_reason": "stop"})
        candidates = refresh_index(self.run_extraction(mock))
        self.assertEqual([c["validation_status"] for c in candidates], ["valid", "duplicate"])
        self.assertEqual(candidates[1]["duplicate_of"], candidates[0]["candidate_id"])

    def test_model_change_creates_new_run(self):
        a = self.run_extraction(model="model-a")
        b = self.run_extraction(model="model-b")
        self.assertNotEqual(a, b)
        self.assertEqual(self.mock.call_count, 2)

    def test_content_change_creates_new_run(self):
        a = self.run_extraction()
        changed = chunk_page(PASSAGE + " More context.", "DOC_fixture", "motor_fault.pdf", 1)[0]
        write_json(self.batch, {"chunks": [changed.model_dump()]})
        b = self.run_extraction()
        self.assertNotEqual(a, b)

    def test_normalizer_never_changes_evidence(self):
        record = TechnicalRecord.model_validate(example(self.chunk))
        record.cause.value = "Insufficient   lubrication"
        normalized = normalize_record(record)
        self.assertEqual(normalized.cause.value, "Insufficient lubrication")
        self.assertEqual(normalized.cause.evidence, record.cause.evidence)

    def test_page_local_chunks_and_pdf_dedup(self):
        docs = self.root / "pdfs"
        docs.mkdir()
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), PASSAGE[:70])
            doc.new_page().insert_text((72, 72), "A different page.")
            doc.new_page()
            doc.save(docs / "a.pdf")
        (docs / "b.pdf").write_bytes((docs / "a.pdf").read_bytes())
        path, payload = parse_directory(docs, self.root / "parsed")
        self.assertEqual([c["page"] for c in payload["chunks"]], [1, 2])
        self.assertEqual(len(payload["documents"]), 1)
        self.assertEqual({i["status"] for i in payload["issues"]}, {"duplicate_pdf", "no_text_review_required"})
        self.assertEqual(parse_directory(docs, self.root / "parsed")[0], path)

    def test_chunk_parameters_and_exact_offsets(self):
        with self.assertRaises(ValueError):
            chunk_page(PASSAGE, "doc", "doc.pdf", 1, 30, 30)
        chunks = chunk_page(PASSAGE, "doc", "doc.pdf", 1, 60, 10)
        for chunk in chunks:
            self.assertEqual(PASSAGE[chunk.start:chunk.end], chunk.text)
        self.assertEqual(chunks[-1].end, len(PASSAGE))

    def test_no_relations_from_cooccurrence(self):
        self.assertEqual(build_relations([{"fmea_record_id": "FMEA_1", "relations": []}], self.root / "relations.json"), [])

    def test_mock_groq_request_configuration(self):
        client = Mock()
        client.chat.completions.create.return_value.choices = [Mock(message=Mock(content='{"records": []}'), finish_reason="stop")]
        raw = groq_completion(client, self.chunk, "openai/gpt-oss-120b")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["model"], "openai/gpt-oss-120b")
        self.assertEqual(raw["finish_reason"], "stop")

    def test_rejected_and_uncertain_decisions_stay_out_of_fmea(self):
        run = self.run_extraction()
        cid = refresh_index(run)[0]["candidate_id"]
        for status in ["rejected", "uncertain"]:
            record_decision(run, self.root / "reviewed", ReviewDecision(candidate_id=cid, decision=status, reviewer="test", note="Not approved"))
            self.assertEqual(build_fmea(run, self.root / "reviewed", self.root / "fmea")[1], [])
        self.assertEqual(len(list((self.root / "reviewed" / run.name / cid / "history").glob("*.json"))), 2)


    def test_changed_candidate_requires_new_review(self):
        run = self.run_extraction()
        cid = refresh_index(run)[0]["candidate_id"]
        record_decision(run, self.root / "reviewed", ReviewDecision(candidate_id=cid, decision="approved", reviewer="test", note="Checked"))
        path = next((run / "validated").glob("*.json"))
        payload = read_json(path)
        payload["candidates"][0]["record"]["component"] = copy.deepcopy(payload["candidates"][0]["record"]["failure_mode"])
        write_json(path, payload)
        with self.assertRaisesRegex(ValueError, "changed after review"):
            build_fmea(run, self.root / "reviewed", self.root / "fmea")

    def test_multiple_causes_remain_separate_relations(self):
        text = "Insufficient lubrication can cause bearing wear. Contamination can cause bearing wear."
        chunk = chunk_page(text, "DOC_causes", "causes.pdf", 1)[0]
        records = []
        for cause, quote in [("Insufficient lubrication", text.split(". ")[0] + "."),
                             ("Contamination", text.split(". ")[1])]:
            ev = {k: getattr(chunk, k) for k in ("document_id", "document_name", "page", "chunk_id")} | {"quote": quote}
            record = dict.fromkeys(FIELDS)
            record["cause"] = {"value": cause, "evidence": [ev]}
            record["failure_mode"] = {"value": "bearing wear", "evidence": [ev]}
            record["relations"] = [{"source": cause, "relation_type": "CAUSES", "target": "bearing wear", "evidence": [ev], "operating_conditions": None}]
            records.append(record)
        result = validate_response({"content": json.dumps({"records": records}), "finish_reason": "stop"}, chunk, "test")
        self.assertTrue(all(c["validation_status"] == "valid" for c in result["candidates"]))
        fmea = [{"fmea_record_id": f"FMEA_{i}", **r} for i, r in enumerate(records)]
        relations = build_relations(fmea, self.root / "multiple.json")
        self.assertEqual(len(relations), 2)
        self.assertEqual({r["source"] for r in relations}, {"Insufficient lubrication", "Contamination"})
        self.assertTrue(all(r["relation_type"] == "CAUSES" for r in relations))

    def test_malformed_record_does_not_discard_valid_sibling(self):
        result = validate_response({"content": json.dumps({"records": [{"garbage": 1}, example(self.chunk)]}), "finish_reason": "stop"}, self.chunk, "test")
        self.assertEqual([c["validation_status"] for c in result["candidates"]], ["invalid", "valid"])

    def test_whitespace_only_quote_rejected(self):
        record = example(self.chunk)
        record["cause"]["evidence"][0]["quote"] = " "
        self.assertTrue(validate_record(TechnicalRecord.model_validate(record), {self.chunk.chunk_id: self.chunk}))


if __name__ == "__main__":
    unittest.main()
