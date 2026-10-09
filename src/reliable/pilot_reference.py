"""Create an editable, source-grounded assistant draft; never label it human ground truth."""
import argparse
from pathlib import Path
from src.io_utils import read_json, write_json
from src.reliable.evaluate import template


def create(batch):
    result = template(batch)
    result.update(review_status="assistant_draft", reviewer="Codex/source-text inspection; human verification pending",
                  notes="Nonexhaustive expected facts. Verify against PDF, edit labels/aliases and add missing facts. Never score this as independent human ground truth.")
    sections = {s["section_id"]: s for s in batch["sections"]}
    refs = {s["section_id"]: s for s in result["sections"]}
    for ref in refs.values():
        ref["review_status"] = "assistant_draft"
        ref["notes"] = "Nonexhaustive; unlisted extra claims need adjudication, not automatic hallucination labels."

    def concept(text, kind):
        return {"text": text, "kind": kind}

    def evidence(sid, needles):
        found = []
        for needle in needles:
            p = next(p for p in sections[sid]["paragraphs"] if needle in p["cleaned_text"])
            ev = {"paragraph_id": p["paragraph_id"], "quote": p["cleaned_text"]}
            if ev not in found:
                found.append(ev)
        return found

    def add(sid, subject, sk, relation, obj, ok, qualifier, needles, context=False):
        row = {"subject": concept(subject, sk), "relation": relation, "object": concept(obj, ok),
               "qualifier": qualifier, "operating_conditions": None, "evidence": evidence(sid, needles),
               "needs_context_review": context, "review_note": "Assistant draft expectation; verify source semantics and role assignment."}
        refs[sid]["expected_relations"].append(row)
        return row

    refs["overview"]["tags"] = ["bullet/list", "mentions", "introductory_causal_sentence"]
    refs["overview"]["expected_concepts"] = [concept("Misalignment", "phenomenon"), concept("Bearing wear", "failure_mode")]
    refs["overview"]["notes"] += " Contents entries alone do not establish causality. The introductory paragraph does contain a separate causal assertion."
    add("fault-01", "transient voltages", "phenomenon", "CAUSES", "insulation breakdown", "failure_mode", "can", ["These tran-"])
    add("fault-01", "insulation breakdown", "failure_mode", "LEADS_TO", "early motor failure", "effect", "leads to", ["Impact:"])
    add("fault-01", "transient voltages", "phenomenon", "DETECTED_BY", "Fluke 435-II Three-Phase Power Quality Analyzer", "detection_method", "asserted", ["1 Transient", "Instrument to measure"], True)
    refs["fault-01"]["tags"] = ["simple_causal_relation", "diagnostic_instrument", "ambiguous_association"]
    forbidden = dict(refs["fault-01"]["expected_relations"][-1])
    forbidden["subject"] = concept("insulation breakdown", "failure_mode")
    refs["fault-01"]["forbidden_relations"].append(forbidden)
    for s, sk, o, ok, q in [("voltage imbalance", "phenomenon", "excessive current flow", "phenomenon", "creates"),
                              ("excessive current flow", "phenomenon", "increased operating temperatures", "phenomenon", "increases"),
                              ("increased operating temperatures", "phenomenon", "insulation breakdown", "failure_mode", "leading to")]:
        add("fault-02", s, sk, "CAUSES", o, ok, q, ["Imbalance creates"])
    refs["fault-02"]["tags"] = ["multi_step_causal_chain", "difficult_layout"]
    forbidden = dict(refs["fault-02"]["expected_relations"][0])
    forbidden["object"] = concept("insulation breakdown", "failure_mode")
    refs["fault-02"]["forbidden_relations"].append(forbidden)
    add("fault-03", "decrease in motor efficiency", "phenomenon", "LEADS_TO", "added cost", "effect", "results in", ["Impact:"])
    refs["fault-03"]["tags"] = ["simple_causal_relation", "technical_units"]
    add("fault-04", "impedance mismatch between source and load", "phenomenon", "CAUSES", "reflections", "phenomenon", "when", ["Reflections are generated"])
    refs["fault-04"]["tags"] = ["causal_relation", "ambiguous_diagnostic_scope"]
    add("fault-05", "protective earth current flow", "phenomenon", "CAUSES", "circuit trip", "failure_mode", "due to", ["Impact:"])
    refs["fault-05"]["tags"] = ["simple_causal_relation", "difficult_layout"]
    for symptom in ["excessive current draw", "insufficient torque", "overheating"]:
        add("fault-06", "motor overload", "failure_mode", "HAS_SYMPTOM", symptom, "symptom", "accompany", ["primary symptoms"])
    refs["fault-06"]["tags"] = ["symptoms", "role_distinction"]
    add("fault-07", "misalignment", "failure_mode", "DETECTED_BY", "Fluke 810 Vibration Tester", "detection_method", "potential", ["to identify potential misalignment"])
    add("fault-07", "misalignment", "failure_mode", "MITIGATED_BY", "correction using Fluke 830 Laser Shaft Alignment Tool", "maintenance_action", "asserted", ["to diagnose and correct misalignment"])
    refs["fault-07"]["tags"] = ["diagnostic_instrument", "maintenance_recommendation", "bullet/list"]
    add("fault-08", "Dirt accumulation", "cause", "CAUSES", "Imbalance", "failure_mode", "can", ["Imbalance can be caused", "Dirt accumulation"])
    refs["fault-08"]["tags"] = ["explicit_causal_list", "multi_paragraph_evidence"]
    add("fault-09", "excessive clearance between rotating and stationary elements", "cause", "CAUSES", "rotating looseness", "failure_mode", "is caused by", ["Rotating looseness is caused"])
    refs["fault-09"]["tags"] = ["bullet/list", "cause_vs_definition"]
    for cause in ["Inadequate or incorrect lubrication", "Shaft misalignment"]:
        add("fault-10", cause, "cause", "CAUSES", "bearing failure", "failure_mode", "can be caused", ["Bearing failure can be caused"])
    add("fault-10", "bearing failure", "failure_mode", "HAS_SYMPTOM", "increased drag", "symptom", "has", ["A failed bearing has increased drag"])
    refs["fault-10"]["tags"] = ["explicit_causal_list", "symptoms", "fmea_seed"]
    add("fault-11", "irregularity in machine mounting feet", "cause", "CAUSES", "soft foot", "failure_mode", "can be caused", ["soft foot can be caused"])
    refs["fault-11"]["tags"] = ["conditional_context", "bullet/list"]
    add("fault-12", "angular or offset force on pump", "cause", "CAUSES", "motor/pump shaft misalignment", "failure_mode", "causes", ["Those forces can put"])
    refs["fault-12"]["tags"] = ["multi_step_causal_chain", "maintenance_recommendation"]
    add("fault-13", "arcing across bearing surfaces", "phenomenon", "CAUSES", "pitting and fluting", "failure_mode", "create", ["Impact:"])
    refs["fault-13"]["tags"] = ["multi_step_causal_chain", "operating_conditions", "diagnostic_instrument"]
    refs["strategies"]["tags"] = ["maintenance_recommendation", "bullet/list", "conditional_threshold"]
    refs["strategies"]["expected_concepts"] = [concept("Document operating condition, machine specifications and performance tolerance ranges", "maintenance_action"),
                                               concept("Capture and document critical measurements", "maintenance_action")]
    refs["strategies"]["notes"] += " General recommendations; do not attach them to every fault. Preserve the context-dependent threshold, never make it universal."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise SystemExit("Refusing to overwrite an existing reference")
    write_json(args.output, create(read_json(args.sections)))
    print(args.output)


if __name__ == "__main__":
    main()
