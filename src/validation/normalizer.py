"""Conservative display normalization; quotations and terminology stay intact."""
from src.extraction.schemas import FIELDS, TechnicalRecord


def normalize_record(record: TechnicalRecord):
    result = record.model_copy(deep=True)
    for name in FIELDS:
        field = getattr(result, name)
        if field:
            field.value = " ".join(field.value.split())
    for relation in result.relations:
        relation.source = " ".join(relation.source.split())
        relation.target = " ".join(relation.target.split())
        if relation.operating_conditions:
            relation.operating_conditions.value = " ".join(relation.operating_conditions.value.split())
    return result
