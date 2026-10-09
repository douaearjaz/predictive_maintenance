"""Mechanical validation is not human confirmation of technical correctness."""
from src.extraction.schemas import FIELDS, TechnicalRecord


def validate_record(record: TechnicalRecord, chunks):
    errors = []
    groups = [(name, getattr(record, name).evidence) for name in FIELDS if getattr(record, name)]
    for i, relation in enumerate(record.relations):
        groups.append((f"relations[{i}]", relation.evidence))
        if relation.operating_conditions:
            groups.append((f"relations[{i}].operating_conditions", relation.operating_conditions.evidence))
        values = {name: getattr(record, name).value if getattr(record, name) else None for name in FIELDS}
        allowed = {
            "CAUSES": [(values["cause"], values["failure_mode"])],
            "RESULTS_IN": [(values["failure_mode"], values["effect"]), (values["failure_mode"], values["symptom"])],
            "DETECTED_BY": [(values["failure_mode"], values["detection_method"]), (values["symptom"], values["detection_method"])],
        }
        if (relation.source, relation.target) not in allowed[relation.relation_type]:
            errors.append(f"relations[{i}]: endpoints do not match supported fields")
    for label, evidence_list in groups:
        for evidence in evidence_list:
            chunk = chunks.get(evidence.chunk_id)
            if chunk is None:
                errors.append(f"{label}: unknown chunk")
                continue
            if any(getattr(evidence, key) != getattr(chunk, key) for key in ("document_id", "document_name", "page")):
                errors.append(f"{label}: provenance mismatch")
            if not evidence.quote.strip() or evidence.quote not in chunk.text:
                errors.append(f"{label}: quotation is not an exact nonempty source substring")
    return errors
