"""Map a feature row to measurement evidence, without asserting a diagnosis."""
import csv
import json
from pathlib import Path


def map_row(row, mapping):
    measurements = []
    for rule in mapping['measurements']:
        value = row[rule['column']]
        measurements.append({'property': rule['property'],
            'value': float(value) if value != '' else None, 'unit': rule['unit'],
            'ontology_context_id': rule['ontology_context_id'],
            'relation': 'measurement_about_component',
            'fuzzy_state': None})
    return {'recording_id': row['recording_id'], 'channel': row['channel'],
        'segment_index': int(row['segment_index']),
        'start_sample': int(row['start_sample']), 'end_sample_exclusive': int(row['end_sample_exclusive']),
        'operating_context': {'load_hp': float(row['load_hp']),
            'rpm': float(row['rpm']) if row['rpm'] else None},
        'measurements': measurements, 'diagnosis': None,
        'note': 'Fault label is deliberately excluded from inference evidence. No ontology fact is asserted.'}


if __name__ == '__main__':
    mapping = json.loads(Path('analysis/measurement_mapping/mapping.json').read_text())
    with Path('analysis/cwru_features/features.csv').open(newline='') as f:
        row = next(csv.DictReader(f))
    observation = map_row(row, mapping)
    Path('analysis/measurement_mapping/example_observation.json').write_text(json.dumps(observation,indent=2)+'\n')
    print(json.dumps(observation,indent=2))
