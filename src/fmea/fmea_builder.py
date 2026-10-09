"""Only explicitly approved, provenance-valid candidates become FMEA records."""
import csv
import json
from pathlib import Path
from src.extraction.extractor import refresh_index
from src.extraction.schemas import Chunk, FIELDS, ReviewDecision, TechnicalRecord
from src.io_utils import digest, read_json, write_json
from src.validation.validator import validate_record


def build_fmea(run_dir, review_root, output_root):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    chunks = {c["chunk_id"]: Chunk.model_validate(c) for c in manifest["chunks"]}
    candidates = refresh_index(run_dir)
    records, excluded = [], []
    for candidate in candidates:
        cid = candidate["candidate_id"]
        decision_path = Path(review_root) / manifest["run_id"] / cid / "decision.json"
        if not decision_path.exists():
            excluded.append({"candidate_id": cid, "reason": "not_reviewed"})
            continue
        decision = read_json(decision_path)
        ReviewDecision.model_validate({k: decision[k] for k in ReviewDecision.model_fields})
        if decision["candidate_id"] != cid or decision["run_id"] != manifest["run_id"]:
            raise ValueError("Review identity mismatch")
        if decision["decision"] != "approved" or candidate["validation_status"] != "valid":
            excluded.append({"candidate_id": cid, "reason": decision["decision"]})
            continue
        if decision["record_hash"] != digest(candidate["record"]):
            raise ValueError(f"Candidate changed after review: {cid}")
        record = TechnicalRecord.model_validate(candidate["record"])
        errors = validate_record(record, chunks)
        if errors:
            raise ValueError(f"Evidence failed revalidation: {cid}: {errors}")
        records.append({"fmea_record_id": "FMEA_" + cid.removeprefix("CAND_"),
                        "candidate_id": cid, "review_status": "approved", "review": decision,
                        **record.model_dump(), "severity": None, "occurrence": None,
                        "detection_rating": None, "rpn": None})
    folder = Path(output_root) / manifest["run_id"]
    write_json(folder / "fmea.json", records)
    write_json(folder / "excluded.json", excluded)
    columns = ["fmea_record_id", "candidate_id", "review_status"]
    for name in FIELDS:
        columns.extend([name, name + "_evidence"])
    columns.extend(["severity", "occurrence", "detection_rating", "rpn"])
    with (folder / "fmea.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = {k: record[k] for k in columns if k in record and k not in FIELDS}
            for name in FIELDS:
                field = record[name]
                row[name] = field["value"] if field else ""
                row[name + "_evidence"] = json.dumps(field["evidence"], ensure_ascii=False) if field else ""
            writer.writerow(row)
    return folder, records
