"""Prepare a motor BN proposal and expert worksheet from accepted graph claims."""
import argparse
import csv
import itertools
import json
import re
from pathlib import Path
from src.reliable.bayesian import validate

RELATIONS = {'CAUSES', 'LEADS_TO', 'HAS_SYMPTOM'}


def build(source, output):
    graph = json.loads(Path(source).read_text())
    concepts = {n['id']: n for n in graph['nodes']}
    claims = [c for c in graph['claims'] if c['relation'] in RELATIONS]
    used = sorted({c[k] for c in claims for k in ('subject', 'object')})
    names, nodes = {}, {}
    for concept in used:
        label = concepts[concept]['label']
        name = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')
        if name in nodes:
            name += '_' + concept[-8:]
        names[concept] = name
        nodes[name] = {'label': label, 'concept_id': concept,
            'states': ['absent', 'present'], 'state_definition': None,
            'parents': [], 'p_present': [], 'parameter_source': None}
    edges = []
    for c in claims:
        parent, child = names[c['subject']], names[c['object']]
        if parent not in nodes[child]['parents']:
            nodes[child]['parents'].append(parent)
        edges.append({'parent': parent, 'child': child, 'source_claim_id': c['id'],
            'source_relation': c['relation'], 'qualifier': c['qualifier'],
            'operating_conditions': c['operating_conditions'], 'evidence': c['evidence'],
            'review_status': 'dependency_proposed_for_expert_review'})
    for node in nodes.values():
        node['parents'].sort()
        node['p_present'] = [None] * (2 ** len(node['parents']))
    model = {'status': 'awaiting_expert_structure_and_probability_review',
        'scope': {'equipment': 'electric motor', 'population': None,
            'operating_conditions': None, 'diagnostic_or_prediction_purpose': None,
            'time_basis': None},
        'parameter_method': 'motor_maintenance_expert_elicitation',
        'source_graph': str(source), 'nodes': nodes, 'edges': edges,
        'excluded_relations': sorted({c['relation'] for c in graph['claims']} - RELATIONS),
        'assumptions_pending_review': [
            'Absent edges encode independence assumptions, not proven absence of effects.',
            'Root causes may share operating or maintenance conditions.',
            'Symptoms may remain dependent after conditioning on modeled parents.',
            'Alternative causes and omitted mechanisms require expert review.',
            'Generic motor and bearing guidance may describe different populations.',
            'Binary states are provisional; current conditions and past exposures must be distinguished.']}
    validate(model, require_probabilities=False)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'motor_bn.json').write_text(json.dumps(model, indent=2, ensure_ascii=False) + '\n')
    fields = ['variable', 'row_index', 'parent_states', 'p_present', 'expert',
              'basis_and_uncertainty', 'review_status']
    count = 0
    with (output / 'expert_probabilities.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for name, node in nodes.items():
            for i, states in enumerate(itertools.product(['absent', 'present'], repeat=len(node['parents']))):
                writer.writerow({'variable': name, 'row_index': i,
                    'parent_states': json.dumps(dict(zip(node['parents'], states))),
                    'review_status': 'pending'})
                count += 1
    with (output / 'expert_variables.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['variable', 'source_label', 'present_definition', 'absent_definition',
                         'measurement_or_threshold', 'time_window', 'expert', 'review_status'])
        for name, node in nodes.items():
            writer.writerow([name, node['label'], '', '', '', '', '', 'pending'])
    with (output / 'expert_dependencies.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['parent', 'child', 'source_claim_id', 'source_relation', 'decision', 'reason', 'expert'])
        for edge in edges:
            writer.writerow([edge[k] for k in ['parent', 'child', 'source_claim_id', 'source_relation']] + ['', '', ''])
    return {'variables': len(nodes), 'source_dependencies': len(edges), 'probability_rows': count}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='analysis/motor_ontology/motor_model.json')
    parser.add_argument('--output', default='analysis/motor_bayesian')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))
