"""Export explicit candidate claims; never infer links from field co-occurrence."""
from src.io_utils import digest, write_json


def build_relations(fmea_records, output_path):
    relations = []
    for record in fmea_records:
        for claim in record["relations"]:
            relations.append({"relation_id": "REL_" + digest([record["fmea_record_id"], claim])[:24],
                              **claim, "linked_fmea_record_id": record["fmea_record_id"],
                              "review_status": "pending"})
    write_json(output_path, relations)
    return relations
