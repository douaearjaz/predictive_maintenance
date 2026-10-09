"""Durable atomic extraction, exact source validation and content-bound review."""
import fcntl
import json
import os
import re
from pathlib import Path
from pydantic import ValidationError
from src.extraction.extractor import DEFAULT_MODEL, make_client
from src.io_utils import digest, read_json, write_json
from src.reliable.schema import Extraction, Statement, Mention, Ambiguity, PROMPT, PROMPT_VERSION
from src.reliable.sections import evidence_span, now

VALIDATOR_VERSION = "atomic-evidence-v1"


def validate(raw, section, response_id):
    result = {"section_id": section["section_id"], "candidates": [], "issues": []}
    if raw.get("finish_reason") != "stop":
        result["issues"].append("Incomplete/refused response; preserved without automatic retry")
        return result
    try:
        payload = json.loads(raw["content"])
        if not isinstance(payload, dict) or set(payload) != {"statements", "mentions", "ambiguities"}:
            raise ValueError("Expected statements, mentions and ambiguities")
        if any(not isinstance(v, list) for v in payload.values()):
            raise ValueError("Output collections must be lists")
    except (ValueError, KeyError, TypeError) as exc:
        result["issues"].append(f"Malformed output: {type(exc).__name__}")
        return result
    for category, model in [("statements", Statement), ("mentions", Mention), ("ambiguities", Ambiguity)]:
        for i, value in enumerate(payload[category]):
            candidate = {"candidate_id": "ATOM_" + digest([response_id, category, i])[:24],
                         "section_id": section["section_id"], "category": category, "raw_record": value,
                         "record": None, "schema_valid": False, "evidence_valid": False,
                         "semantic_review_status": "pending", "issues": [], "warnings": [], "resolved_evidence": []}
            try:
                record = model.model_validate(value).model_dump()
                candidate["record"] = record
                candidate["schema_valid"] = True
                refs = record["evidence"][:]
                if record.get("operating_conditions"):
                    refs += record["operating_conditions"]["evidence"]
                candidate["resolved_evidence"] = [evidence_span(e, section) for e in refs]
                candidate["evidence_valid"] = True
                if category == "statements":
                    quoted = " ".join(e["quote"] for e in refs).casefold()
                    if any(record[side]["text"].casefold() not in quoted for side in ("subject", "object")):
                        candidate["warnings"].append("endpoint_not_literal_in_quote_check_full_paragraph")
                    if record["relation"] == "DETECTED_BY" and record["subject"]["text"].casefold() not in quoted:
                        candidate["warnings"].append("instrument_scope_requires_heading_and_context_review")
                    if record["qualifier"] == "asserted" and re.search(r"\b(can|may|might|often|sometimes)\b", quoted):
                        candidate["warnings"].append("modal_word_in_quote_check_qualifier")
                    if record["relation"] == "HAS_FUNCTION" and (record["subject"]["kind"] != "component" or record["object"]["kind"] != "function"):
                        candidate["issues"].append("HAS_FUNCTION requires component → function")
                    if record["relation"] == "HAS_SYMPTOM" and record["object"]["kind"] != "symptom":
                        candidate["issues"].append("HAS_SYMPTOM target must be symptom")
                    if record["needs_context_review"]:
                        candidate["warnings"].append("context_association_requires_review")
                    if record["subject"]["kind"] == "unknown" or record["object"]["kind"] == "unknown":
                        candidate["warnings"].append("unresolved_endpoint_role")
                    if record["relation"] == "DETECTED_BY" and record["object"]["kind"] != "detection_method":
                        candidate["issues"].append("DETECTED_BY target must be detection_method")
                    if record["relation"] == "MITIGATED_BY" and record["object"]["kind"] != "maintenance_action":
                        candidate["issues"].append("MITIGATED_BY target must be maintenance_action")
                    if record["relation"] == "HAS_FAILURE_MODE" and (record["subject"]["kind"] != "component" or record["object"]["kind"] != "failure_mode"):
                        candidate["issues"].append("HAS_FAILURE_MODE requires component → failure_mode")
                    if record["qualifier"] != "asserted" and not any(record["qualifier"].casefold() in e["quote"].casefold() for e in refs):
                        candidate["warnings"].append("qualifier_not_literal_in_evidence")
            except ValidationError as exc:
                candidate["issues"] = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            except ValueError as exc:
                candidate["issues"].append(str(exc))
            result["candidates"].append(candidate)
    return result


def section_input(section):
    return {k: section[k] for k in ("document_id", "document_name", "section_id", "section", "pages", "issues")} | {
        "context": section.get("context", ""),
        "paragraphs": [{k: p[k] for k in ("paragraph_id", "page", "cleaned_text", "issues")} for p in section["paragraphs"]]}


def extract(batch_path, output="data/pilot/runs", model=None, max_sections=15, complete=None,
            source_kind="llm", section_ids=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    if max_sections < 1 or max_sections > 15:
        raise ValueError("Pilot permits 1–15 new section requests per invocation")
    batch = read_json(batch_path)
    sections = batch["sections"]
    if section_ids:
        if not set(section_ids) <= {s["section_id"] for s in sections}:
            raise ValueError("Unknown section selection")
        sections = [s for s in sections if s["section_id"] in section_ids]
    if not sections or len(sections) > 15 or len({s["document_id"] for s in sections}) != 1:
        raise ValueError("Pilot requires 1–15 sections from one PDF")
    model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    contextual = any(section.get("context") for section in sections)
    prompt = PROMPT
    if contextual:
        prompt += "\nFor source tables, use supplied inspected context to preserve column/row associations. Context is navigation metadata, never quote it as source evidence. Quote the real fault cell AND cause cell for a causal claim. A troubleshooting cause is possible, not sufficient by itself. Link a row-specific remedy as CAUSE -> MITIGATED_BY -> action so it is not attached to all causes of the same fault. A tool name is not an action: name the actual operation. Use failure_mode for an explicit unwanted functional state (fails to start, defective winding, bearing failure); preserve symptoms separately. Keep quoted text exactly as supplied, including line-end hyphens. Use full sentences or full table cells to preserve context."
    config = {"model": model, "provider": "groq" if source_kind == "llm" else "local",
              "source_kind": source_kind, "temperature": 0, "seed": 42, "max_completion_tokens": 8192,
              "response_format": {"type": "json_object"}, "prompt": prompt, "prompt_version": PROMPT_VERSION + ("-table-context-v1" if contextual else ""),
              "validator_version": VALIDATOR_VERSION, "schema": Extraction.model_json_schema(),
              **{k: batch[k] for k in ("parser_version", "segmentation_version", "cleaning_version", "pymupdf_version")}}
    run_id = digest([config, sections])[:24]
    run = Path(output) / run_id
    run.mkdir(parents=True, exist_ok=True)
    with (run / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This pilot run is already active") from None
        manifest = {"run_id": run_id, "created_at": now(), "batch_id": batch["batch_id"],
                    "batch_path": str(Path(batch_path).resolve()), "config": config, "sections": sections}
        if not (run / "manifest.json").exists():
            write_json(run / "manifest.json", manifest)
        client, sent = None, 0
        for section in sections:
            response_id = digest([config, section])
            raw_path = run / "raw" / f"{response_id}.json"
            if raw_path.exists():
                continue
            if sent >= max_sections:
                break
            try:
                if complete:
                    raw = complete(section, model)
                else:
                    client = client or make_client()
                    response = client.chat.completions.create(
                        model=model, temperature=0, seed=42, max_completion_tokens=8192,
                        response_format={"type": "json_object"},
                        messages=[{"role": "system", "content": prompt + "\nSchema:\n" + json.dumps(config["schema"])},
                                  {"role": "user", "content": json.dumps(section_input(section), ensure_ascii=False)}])
                    choice = response.choices[0]
                    raw = {"content": choice.message.content, "finish_reason": choice.finish_reason,
                           "provider_response_id": response.id, "returned_model": response.model,
                           "usage": response.usage.model_dump() if response.usage else None}
                write_json(raw_path, {**raw, "created_at": now(), "section_id": section["section_id"]})
                sent += 1
            except Exception as exc:
                event = {"created_at": now(), "section_id": section["section_id"], "error_type": type(exc).__name__,
                         "status_code": getattr(exc, "status_code", None)}
                write_json(run / "errors" / f"{digest(event)}.json", event)
                snapshot(run)
                raise RuntimeError(f"Pilot paused ({type(exc).__name__}); cached responses preserved. Resume same command. Run: {run}") from None
        snapshot(run)
    return run


def inspect(run):
    """Revalidate raw responses in memory. Never trust/edit cached validation flags."""
    run = Path(run)
    manifest = read_json(run / "manifest.json")
    if manifest["run_id"] != digest([manifest["config"], manifest["sections"]])[:24]:
        raise ValueError("Manifest integrity mismatch")
    results, missing, seen = [], [], {}
    for section in manifest["sections"]:
        rid = digest([manifest["config"], section])
        path = run / "raw" / f"{rid}.json"
        if not path.exists():
            missing.append(section["section_id"])
            continue
        result = validate(read_json(path), section, rid)
        for c in result["candidates"]:
            if c["record"] is not None:
                key = digest([c["section_id"], c["category"], c["record"]])
                if key in seen:
                    c["duplicate_of"] = seen[key]
                else:
                    seen[key] = c["candidate_id"]
        results.append(result)
    return {"run_id": manifest["run_id"], "source_kind": manifest["config"]["source_kind"],
            "responses": len(results), "total_sections": len(manifest["sections"]), "missing_sections": missing,
            "results": results, "validator_version": VALIDATOR_VERSION,
            "validator_code_hash": digest([Path(__file__).read_text(), Path(__file__).with_name("sections.py").read_text()])}


def snapshot(run):
    report = inspect(run)
    path = Path(run) / "validation" / f"{digest(report)}.json"
    if not path.exists():
        write_json(path, report)
    return path


def candidates(run):
    return [c for r in inspect(run)["results"] for c in r["candidates"]]


def review(run, candidate_id, decision, reviewer, note, reviewer_kind="human"):
    if decision not in {"accepted", "rejected", "uncertain"} or reviewer_kind not in {"human", "assistant"}:
        raise ValueError("Invalid review decision or reviewer kind")
    if not reviewer.strip() or not note.strip():
        raise ValueError("Reviewer and a semantic review note are required")
    candidate = next((c for c in candidates(run) if c["candidate_id"] == candidate_id), None)
    if candidate is None:
        raise ValueError("Unknown candidate")
    if decision == "accepted" and (not candidate["schema_valid"] or not candidate["evidence_valid"] or candidate["issues"] or candidate.get("duplicate_of")):
        raise ValueError("Cannot accept invalid or duplicate content")
    item = {"run_id": Path(run).name, "candidate_id": candidate_id, "candidate_hash": digest(candidate),
            "decision": decision, "reviewer": reviewer, "reviewer_kind": reviewer_kind,
            "note": note, "reviewed_at": now()}
    folder = Path(run) / "reviews" / candidate_id
    write_json(folder / f"{digest(item)}.json", item)
    return item


def latest_review(run, candidate):
    history = [read_json(p) for p in (Path(run) / "reviews" / candidate["candidate_id"]).glob("*.json")]
    if not history:
        return None
    item = max(history, key=lambda r: r["reviewed_at"])
    if item["run_id"] != Path(run).name or item["candidate_id"] != candidate["candidate_id"] or item["candidate_hash"] != digest(candidate):
        raise ValueError("Candidate or evidence changed after review; new review required")
    return item
