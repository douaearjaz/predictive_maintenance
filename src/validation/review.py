"""Explicit review decisions, immutable history, and candidate integrity binding."""
from datetime import datetime, timezone
from pathlib import Path
from src.extraction.extractor import refresh_index
from src.extraction.schemas import Chunk, ReviewDecision, TechnicalRecord
from src.io_utils import digest, read_json, write_json
from src.validation.validator import validate_record


def record_decision(run_dir, review_root, decision: ReviewDecision):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    candidates = refresh_index(run_dir)
    matches = [c for c in candidates if c["candidate_id"] == decision.candidate_id]
    if not matches:
        raise ValueError("Unknown candidate ID")
    candidate = matches[0]
    if decision.decision == "approved":
        if candidate["validation_status"] != "valid":
            raise ValueError("Only mechanically valid, nonduplicate candidates can be approved")
        chunks = {c["chunk_id"]: Chunk.model_validate(c) for c in manifest["chunks"]}
        errors = validate_record(TechnicalRecord.model_validate(candidate["record"]), chunks)
        if errors:
            raise ValueError("Candidate failed provenance validation: " + "; ".join(errors))
    folder = Path(review_root) / manifest["run_id"] / decision.candidate_id
    item = {**decision.model_dump(), "record_hash": digest(candidate["record"]),
            "run_id": manifest["run_id"], "record": candidate["record"],
            "reviewed_at": datetime.now(timezone.utc).isoformat()}
    write_json(folder / "history" / f"{digest(item)}.json", item)
    write_json(folder / "decision.json", item)
    return item
