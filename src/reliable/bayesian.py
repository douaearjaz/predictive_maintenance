"""Small binary Bayesian network: explicit CPTs and exact enumeration.

No dependencies beyond Python. Intended for small reviewed networks.
"""
import argparse
import itertools
import json
import math
from graphlib import TopologicalSorter, CycleError
from pathlib import Path


def validate(model, require_probabilities=True):
    nodes = model['nodes']
    if not nodes:
        raise ValueError('The model has no variables')
    for name, node in nodes.items():
        parents = node['parents']
        if len(set(parents)) != len(parents) or any(p not in nodes for p in parents):
            raise ValueError(f'{name}: duplicate or unknown parent')
        if len(node['p_present']) != 2 ** len(parents):
            raise ValueError(f'{name}: one probability is required for every parent configuration')
        for p in node['p_present']:
            if p is None and not require_probabilities:
                continue
            if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError(f'{name}: missing or invalid probability; fill the CPT first')
    try:
        return list(TopologicalSorter({n: set(v['parents']) for n, v in nodes.items()}).static_order())
    except CycleError as exc:
        raise ValueError('Bayesian structure contains a cycle; review the causal/time model') from exc


def infer(model, query, evidence=None):
    """Return P(query=present | evidence); CPT order is 00, 01, 10, 11."""
    order = validate(model)
    nodes, evidence = model['nodes'], dict(evidence or {})
    if query not in nodes or any(n not in nodes for n in evidence):
        raise ValueError('Unknown query or evidence variable')
    if any(type(v) is not bool for v in evidence.values()):
        raise ValueError('Evidence must use true/false; omit unknown observations')
    relevant, pending = set(), [query, *evidence]
    while pending:
        name = pending.pop()
        if name not in relevant:
            relevant.add(name)
            pending.extend(nodes[name]['parents'])
    order = [n for n in order if n in relevant]
    free = [n for n in order if n not in evidence]
    if len(free) > 22:
        raise ValueError('More than 22 unobserved relevant variables; use variable elimination for this query')
    masses = [0.0, 0.0]
    for states in itertools.product((False, True), repeat=len(free)):
        assignment = {**evidence, **dict(zip(free, states))}
        joint = 1.0
        for name in order:
            node, row = nodes[name], 0
            for parent in node['parents']:
                row = 2 * row + int(assignment[parent])
            p = node['p_present'][row]
            joint *= p if assignment[name] else 1 - p
        masses[int(assignment[query])] += joint
    total = sum(masses)
    if total == 0:
        raise ValueError('The evidence has zero probability under this model')
    return {'query': query, 'p_present': masses[1] / total,
            'p_absent': masses[0] / total, 'evidence_probability': total,
            'model_status': model.get('status', 'unspecified')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('--query', required=True)
    parser.add_argument('--evidence', default='{}', help='JSON object of variable: true/false')
    args = parser.parse_args()
    try:
        print(json.dumps(infer(json.loads(args.model.read_text()), args.query,
                               json.loads(args.evidence)), indent=2))
    except ValueError as exc:
        parser.exit(2, str(exc) + '\n')
