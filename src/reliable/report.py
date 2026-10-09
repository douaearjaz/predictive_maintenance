"""Readable source and review packet; original artifacts are never modified."""
import json
from pathlib import Path
from src.io_utils import digest, read_json
from src.reliable.pipeline import inspect, latest_review


def report(run):
    state = inspect(run)
    manifest = read_json(Path(run) / "manifest.json")
    sections = {s["section_id"]: s for s in manifest["sections"]}
    lines = ["# Atomic extraction review packet", "", f"Run: `{state['run_id']}`. Source: {state['source_kind']}.",
             f"Responses: {state['responses']}/{state['total_sections']}.", "",
             "Check source context, endpoint roles, direction, modality, conditions and diagnostic scope before acceptance.", ""]
    for result in state["results"]:
        section = sections[result["section_id"]]
        lines += [f"## {section['section']}", "", f"Physical PDF page(s): {section['pages']}.", "", "### Source paragraphs", ""]
        for p in section["paragraphs"]:
            lines += [f"**{p['paragraph_id']}** — PDF box `{p['bbox']}`", "", p["cleaned_text"], ""]
        if result["issues"]:
            lines += ["Output issues: " + "; ".join(result["issues"]), ""]
        for c in result["candidates"]:
            decision = latest_review(run, c)
            status = f"{decision['decision']} ({decision['reviewer_kind']}: {decision['reviewer']})" if decision else "pending"
            lines += [f"### {c['candidate_id']} ({c['category']})", "",
                      f"Schema valid: {c['schema_valid']}; evidence valid: {c['evidence_valid']}; review: {status}.", ""]
            r = c["record"]
            if r and c["category"] == "statements":
                lines += [f"**{r['subject']['text']}** ({r['subject']['kind']}) → **{r['relation']}** → **{r['object']['text']}** ({r['object']['kind']})",
                          "", f"Qualifier: `{r['qualifier']}`. Conditions: `{r['operating_conditions']}`.", ""]
            elif r:
                lines += [str(r.get("concept", r.get("description"))), ""]
            else:
                lines += ["Malformed record: " + json.dumps(c["raw_record"], ensure_ascii=False), ""]
            for ev in c["resolved_evidence"]:
                lines += [f"Evidence `{ev['paragraph_id']}`, cleaned offsets {ev['clean_start']}:{ev['clean_end']}, original offsets {ev['original_start']}:{ev['original_end']}:",
                          "", "> " + ev["quote"], ""]
            if c["issues"] or c["warnings"]:
                lines += ["Checks: " + "; ".join(c["issues"] + c["warnings"]), ""]
            if decision:
                lines += ["Review note: " + decision["note"], ""]
    content = "\n".join(lines)
    path = Path(run) / "reports" / f"{digest(content)[:24]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return path
