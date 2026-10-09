"""Conservative, section-local projection of accepted atomic statements. No path closure."""
import csv
import json
from pathlib import Path
from src.extraction.schemas import FIELDS
from src.io_utils import digest, write_json
from src.reliable.pipeline import candidates, latest_review
from src.reliable.sections import now

VERSION = "reviewed-atomic-fmea-v3"


# Explicit, role-specific aliases. Never rewrite extracted records or quotes.
FAILURE_ALIASES = {
    "bearing failure": "bearing failure",
    "failed bearing": "bearing failure",
    "defective motor bearings": "bearing failure",
    "bearings to fail": "bearing failure",
}


def failure_name(endpoint):
    text = endpoint["text"]
    if endpoint["kind"] != "failure_mode":
        return text
    return FAILURE_ALIASES.get(" ".join(text.casefold().split()), text)


def conditions(candidate):
    # Only identical recorded conditions can share a scenario.
    return json.dumps(candidate["record"]["operating_conditions"], sort_keys=True)


def build(run, allow_assistant=False):
    accepted, excluded = [], []
    for candidate in candidates(run):
        decision = latest_review(run, candidate)
        reason = None
        if candidate["category"] != "statements":
            reason = "not_a_statement"
        elif not decision or decision["decision"] != "accepted":
            reason = "not_accepted"
        elif decision["reviewer_kind"] != "human" and not allow_assistant:
            reason = "human_review_required"
        elif not candidate["schema_valid"] or not candidate["evidence_valid"] or candidate["issues"] or candidate.get("duplicate_of"):
            reason = "invalid_or_duplicate"
        if reason:
            excluded.append({"candidate_id": candidate["candidate_id"], "reason": reason})
        else:
            accepted.append({**candidate, "review": decision})
    rows, used = [], set()
    anchors = sorted({(c["section_id"], failure_name(endpoint), conditions(c)) for c in accepted
                      for endpoint in (c["record"]["subject"], c["record"]["object"])
                      if endpoint["kind"] == "failure_mode"})
    for section_id, failure, condition in anchors:
        def matches(endpoint):
            return endpoint["kind"] == "failure_mode" and failure_name(endpoint) == failure

        related = [c for c in accepted if c["section_id"] == section_id and conditions(c) == condition and any(
            matches(c["record"][side]) for side in ("subject", "object"))]
        incoming = [c for c in related if matches(c["record"]["object"]) and c["record"]["relation"] in {"CAUSES", "LEADS_TO"}]
        for cause in incoming or [None]:
            values = {name: [] for name in FIELDS}
            supporting = {}

            def add(field, endpoint, c):
                value = {"value": failure_name(endpoint) if field == "failure_mode" else endpoint["text"],
                         "original_value": endpoint["text"], "statement_id": c["candidate_id"],
                         "qualifier": c["record"]["qualifier"], "operating_conditions": c["record"]["operating_conditions"],
                         "evidence": c["resolved_evidence"]}
                if value not in values[field]:
                    values[field].append(value)
                supporting[c["candidate_id"]] = c

            if cause:
                add("cause", cause["record"]["subject"], cause)
                add("failure_mode", cause["record"]["object"], cause)
            for c in related:
                r = c["record"]
                if matches(r["object"]) and r["relation"] == "HAS_FAILURE_MODE" and r["subject"]["kind"] == "component":
                    add("component", r["subject"], c)
                    add("failure_mode", r["object"], c)
                if not matches(r["subject"]):
                    continue
                field = {"CAUSES": "effect", "LEADS_TO": "effect", "HAS_SYMPTOM": "symptom",
                         "DETECTED_BY": "detection_method", "MITIGATED_BY": "maintenance_action"}.get(r["relation"])
                if field:
                    add(field, r["object"], c)
                    add("failure_mode", r["subject"], c)
            # A remedy for one cause stays with that cause's scenario.
            if cause:
                for c in accepted:
                    r = c["record"]
                    if c["section_id"] == section_id and conditions(c) == condition and r["subject"] == cause["record"]["subject"]:
                        field = {"MITIGATED_BY": "maintenance_action", "DETECTED_BY": "detection_method"}.get(r["relation"])
                        if field:
                            add(field, r["object"], c)
            # Functions are joined only for an explicitly attached component in this section.
            components = {v["value"] for v in values["component"]}
            for c in accepted:
                r = c["record"]
                if c["section_id"] == section_id and conditions(c) == condition and r["relation"] == "HAS_FUNCTION" and r["subject"]["kind"] == "component" and r["subject"]["text"] in components:
                    add("function", r["object"], c)
            if not supporting:
                continue
            used.update(supporting)
            rows.append({"fmea_record_id": "FMEA_" + digest([section_id, failure, condition, sorted(supporting)])[:24],
                         "section_id": section_id, **{k: v or None for k, v in values.items()},
                         "severity": None, "occurrence": None, "detection_rating": None, "rpn": None,
                         "statement_ids": sorted(supporting), "reviews": [c["review"] for c in supporting.values()],
                         "status": "assistant_verified_draft" if any(c["review"]["reviewer_kind"] != "human" for c in supporting.values()) else "human_reviewed_draft"})
    excluded += [{"candidate_id": c["candidate_id"], "reason": "accepted_statement_has_no_direct_fmea_mapping"}
                 for c in accepted if c["candidate_id"] not in used]
    payload = {"builder_version": VERSION, "failure_aliases": FAILURE_ALIASES, "allow_assistant": allow_assistant, "run_id": Path(run).name,
               "records": rows, "excluded": excluded}
    folder = Path(run) / "fmea" / digest(payload)[:24]
    if not (folder / "fmea.json").exists():
        write_json(folder / "fmea.json", {**payload, "created_at": now()})
        columns = ["fmea_record_id", "section_id", "status", *FIELDS, "severity", "occurrence", "detection_rating", "rpn", "statement_ids"]
        with (folder / "fmea.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for record in rows:
                writer.writerow({k: json.dumps(record[k], ensure_ascii=False) if isinstance(record[k], list) else record[k] for k in columns})
    return folder, payload
