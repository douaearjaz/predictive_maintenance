"""Exact, alias-aware reference comparison. Unlisted facts are not automatically hallucinations."""
from pathlib import Path
from src.io_utils import digest, read_json, write_json
from src.reliable.pipeline import inspect
from src.reliable.sections import now

VERSION = "atomic-reference-v2"


def template(batch):
    return {"reference_version": 1, "batch_id": batch["batch_id"], "review_status": "pending",
            "reviewer": None, "aliases": {}, "relation_aliases": {}, "qualifier_aliases": {}, "sections": [
                {"section_id": s["section_id"], "title": s["section"], "tags": [], "review_status": "pending",
                 "exhaustive": False, "aliases": {}, "expected_concepts": [], "expected_relations": [], "forbidden_relations": [],
                 "notes": "Add concepts {text, kind}; relations {subject, relation, object, qualifier, operating_conditions}."}
                for s in batch["sections"]]}


def evaluate(run, reference_path):
    reference = read_json(reference_path)
    manifest = read_json(Path(run) / "manifest.json")
    if reference["batch_id"] != manifest["batch_id"]:
        raise ValueError("Reference set belongs to a different section batch")
    global_aliases = {k.casefold(): v.casefold() for k, v in reference.get("aliases", {}).items()}
    aliases = dict(global_aliases)
    relation_aliases = reference.get("relation_aliases", {})
    qualifier_aliases = {k.casefold(): v.casefold() for k, v in reference.get("qualifier_aliases", {}).items()}

    def text(value):
        value = " ".join(value.split()).casefold()
        return aliases.get(value, value)

    def concept(value):
        return text(value["text"]), value["kind"]

    def relation(value):
        condition = value.get("operating_conditions")
        condition = condition["text"] if isinstance(condition, dict) else condition
        qualifier = " ".join(value["qualifier"].split()).casefold()
        return (concept(value["subject"]), relation_aliases.get(value["relation"], value["relation"]), concept(value["object"]),
                qualifier_aliases.get(qualifier, qualifier), text(condition) if condition else None)

    state = inspect(run)
    results = {r["section_id"]: r for r in state["results"]}
    details = []
    keys = ["correct_concepts", "correct_relations", "missing_concepts", "missing_relations",
            "unsupported_facts", "wrong_role_or_association", "qualifier_or_condition_errors",
            "unassessed_extra_facts", "invalid_candidates"]
    totals = dict.fromkeys(keys, 0)
    evaluated, unreviewed = [], []
    for ref in reference["sections"]:
        sid = ref["section_id"]
        aliases = global_aliases | {k.casefold(): v.casefold() for k, v in ref.get("aliases", {}).items()}
        if sid not in results or results[sid]["issues"]:
            continue
        if ref["review_status"] not in {"human_verified", "assistant_draft"}:
            unreviewed.append(sid)
            continue
        evaluated.append(sid)
        cs, rs, invalid = set(), set(), []
        for candidate in results[sid]["candidates"]:
            r = candidate["record"]
            if not candidate["schema_valid"] or not candidate["evidence_valid"] or candidate["issues"]:
                invalid.append(candidate["candidate_id"])
            if not r:
                continue
            if candidate["category"] == "statements":
                cs.update((concept(r["subject"]), concept(r["object"])))
                rs.add(relation(r))
            elif candidate["category"] == "mentions":
                cs.add(concept(r["concept"]))
        expected_r = {relation(r) for r in ref["expected_relations"]}
        expected_c = {concept(c) for c in ref["expected_concepts"]}
        expected_c.update(c for r in expected_r for c in (r[0], r[2]))
        forbidden = {relation(r)[:3] for r in ref["forbidden_relations"]}
        extras = rs - expected_r
        wrong = {r for r in extras if any((r[0][0], r[2][0]) == (e[0][0], e[2][0]) and r[:3] != e[:3] for e in expected_r)}
        wrong |= {r for r in extras if r[:3] in forbidden}
        modifiers = {r for r in extras if any(r[:3] == e[:3] for e in expected_r)}
        unsupported = {r for r in extras if r[:3] in forbidden}
        remaining = extras - wrong - modifiers - unsupported
        if ref["exhaustive"]:
            unsupported |= remaining
            remaining = set()
        item = {"section_id": sid, "reference_status": ref["review_status"],
                "correct_concepts": sorted(cs & expected_c), "correct_relations": sorted(rs & expected_r, key=repr),
                "missing_concepts": sorted(expected_c - cs), "missing_relations": sorted(expected_r - rs, key=repr),
                "unsupported_facts": sorted(unsupported, key=repr), "wrong_role_or_association": sorted(wrong, key=repr),
                "qualifier_or_condition_errors": sorted(modifiers, key=repr), "unassessed_extra_facts": sorted(remaining, key=repr),
                "invalid_candidates": invalid}
        for k in keys:
            totals[k] += len(item[k])
        details.append(item)
    report = {"evaluation_version": VERSION, "run_id": manifest["run_id"], "config": manifest["config"],
              "reference_hash": digest(reference), "reference_status": reference["review_status"],
              "comparison_rules": {"global_aliases": global_aliases, "relation_aliases": relation_aliases,
                                   "qualifier_aliases": qualifier_aliases, "section_aliases": {s["section_id"]: s.get("aliases", {}) for s in reference["sections"]}},
              "source_kind": state["source_kind"], "response_coverage": f"{state['responses']}/{state['total_sections']}",
              "evaluated_sections": evaluated, "unreviewed_reference_sections": unreviewed,
              "unprocessed_sections": state["missing_sections"], "totals": totals, "details": details,
              "output_issues": [{"section_id": r["section_id"], "issues": r["issues"]} for r in state["results"] if r["issues"]],
              "limitations": "Exact labels with explicit, recorded term/relation/qualifier aliases; endpoint kinds and direction must match; no semantic judge. Nonexhaustive extras need adjudication. Wrong-role and unsupported categories may overlap. Content matches do not imply evidence validity or human approval."}
    path = Path(run) / "evaluations" / f"{digest(report)}.json"
    if not path.exists():
        write_json(path, {**report, "created_at": now()})
    return path, report
