"""Offline PNG/PDF knowledge-graph figures from an existing ontology JSON."""
import argparse
from collections import defaultdict
import math
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch
import networkx as nx

from src.io_utils import digest, read_json, write_json

COLORS = {
    'failure_mode': '#F4A6A0', 'component': '#A9CBE8', 'cause': '#F4D18A',
    'symptom': '#B7D9A5', 'effect': '#D2B6E5', 'phenomenon': '#A9DEDC',
    'detection_method': '#AEBDED', 'maintenance_action': '#A9D9C7',
    'function': '#E7C5DF', 'unknown': '#D9DDE3',
}
VERSION = 'ontology-python-figures-v2-unified'


def wrap(value, width=25):
    return '\n'.join(textwrap.wrap(value, width=width, break_long_words=False))


def draw(ax, statements, concepts, positions=None):
    graph = nx.DiGraph()
    for s in statements:
        graph.add_edge(s['subject'], s['object'])
    if positions is None:
        # Condensation handles cycles without changing or inventing any displayed edge.
        condensed = nx.condensation(graph)
        levels = {}
        for n in nx.topological_sort(condensed):
            levels[n] = max((levels[p] + 1 for p in condensed.predecessors(n)), default=0)
        columns = defaultdict(list)
        for node in graph:
            columns[levels[condensed.graph['mapping'][node]]].append(node)
        positions = {}
        for level, nodes in columns.items():
            nodes.sort(key=lambda n: concepts[n]['label'].casefold())
            for i, node in enumerate(nodes):
                positions[node] = (level * 7.5, (len(nodes) - 1 - 2 * i) * 1.2)
    else:
        graph.add_nodes_from(positions)
    for i, s in enumerate(statements, 1):
        x1, y1 = positions[s['subject']]
        x2, y2 = positions[s['object']]
        forward = x2 > x1
        start = (x1 + (1.7 if forward else -1.7), y1)
        end = (x2 - (1.7 if forward else -1.7), y2)
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=13,
                                    color='#526579', linewidth=1.2, zorder=1,
                                    connectionstyle='arc3,rad=0.0' if forward else 'arc3,rad=0.25'))
        qualifier = '' if s['qualifier'] == 'asserted' else ' · ' + s['qualifier']
        condition = ' · conditional' if s['operating_conditions'] else ''
        label = f'[{i}] ' + s['relation'].lower().replace('_', ' ') + qualifier + condition
        # Stagger labels near their originating node for converging arrows.
        fraction = .35 if len(list(graph.predecessors(s['object']))) > 1 else .65
        ax.text(start[0] + fraction * (end[0] - start[0]),
                y1 + fraction * (y2 - y1), wrap(label, 24), ha='center', va='center',
                fontsize=8, color='#26384B', zorder=3,
                bbox={'facecolor': '#FFFFFF', 'edgecolor': 'none', 'pad': 1.5, 'alpha': .95})
    for node, (x, y) in positions.items():
        concept = concepts[node]
        kind = next((k for k in COLORS if k in concept['kinds']), 'unknown')
        label = wrap(concept['label'])
        if concept.get("source_tag"):
            label += "\n[" + concept["source_tag"] + "]"
        height = max(1.05, .25 * (label.count('\n') + 1) + .25)
        ax.add_patch(FancyBboxPatch((x - 1.7, y - height / 2), 3.4, height,
                     boxstyle='round,pad=0.08', facecolor=COLORS[kind], edgecolor='#536579', zorder=4))
        ax.text(x, y, label, ha='center', va='center', fontsize=9, color='#172C3F', zorder=5)
    ys = [p[1] for p in positions.values()]
    ax.set_xlim(min(p[0] for p in positions.values()) - 2.1, max(p[0] for p in positions.values()) + 2.1)
    ax.set_ylim(min(ys) - 1.2, max(ys) + 1.2)
    ax.axis('off')
    return graph


def evidence_pages(pdf, title, statements):
    lines = [title, 'Arrow references — qualifiers and conditions belong to the claim.', '']
    for i, s in enumerate(statements, 1):
        lines.extend(textwrap.wrap(s['document_name'] + ' · ' + s['section'], 115))
        r = s['original_record']
        text = f'[{i}] {r["subject"]["text"]} → {s["relation"]} → {r["object"]["text"]}. Qualifier: {s["qualifier"]}.'
        lines.extend(textwrap.wrap(text, 115))
        if s['operating_conditions']:
            lines.extend(textwrap.wrap('Conditions: ' + s['operating_conditions']['text'], 115))
        for ev in s['evidence']:
            quote = ev.get('quote', ev.get('original_quote', ''))
            lines.extend(textwrap.wrap(f'Page {ev.get("page", "?")}: {quote}', 115))
        lines.append('')
    for offset in range(0, len(lines), 48):
        fig = plt.figure(figsize=(14, 10))
        fig.text(.05, .95, '\n'.join(lines[offset:offset + 48]), va='top', fontsize=10, linespacing=1.4)
        pdf.savefig(fig)
        plt.close(fig)


def unified_positions(concepts, statements):
    graph = nx.DiGraph()
    graph.add_nodes_from(concepts)
    graph.add_edges_from((s['subject'], s['object']) for s in statements)
    components = sorted(nx.weakly_connected_components(graph), key=lambda nodes: (-len(nodes), sorted(nodes)))
    layouts = []
    for nodes in components:
        sub = graph.subgraph(nodes)
        condensed = nx.condensation(sub)
        levels = {}
        for n in nx.topological_sort(condensed):
            levels[n] = max((levels[p] + 1 for p in condensed.predecessors(n)), default=0)
        columns = defaultdict(list)
        for node in nodes:
            columns[levels[condensed.graph['mapping'][node]]].append(node)
        local = {}
        for level, members in columns.items():
            members.sort(key=lambda n: (concepts[n]['label'], n))
            for i, node in enumerate(members):
                local[node] = (level * 7.5, i * 2.6)
        layouts.append((local, max(x for x, y in local.values()) + 6,
                        max(y for x, y in local.values()) + 4.5))
    # Pack disconnected components on ONE axes, without adding artificial edges.
    positions = {}
    yoffset = 0
    for offset in range(0, len(layouts), 2):
        row = layouts[offset:offset + 2]
        xoffset = 0
        for local, width, height in row:
            positions.update({n: (x + xoffset, -y - yoffset) for n, (x, y) in local.items()})
            xoffset += width + 2
        yoffset += max(height for local, width, height in row)
    return graph, positions


def generate(ontology, output=None):
    payload = read_json(ontology)
    target = Path(output) if output else Path(ontology).parent / 'figures' / digest([VERSION, payload])[:16]
    if (target / 'manifest.json').exists():
        return target
    if not payload['statements']:
        raise ValueError('No statements to plot.')
    target.mkdir(parents=True, exist_ok=True)
    sections = sorted({(s['document_id'], s['section_id'], s['document_name'], s['section'])
                       for s in payload['statements']})
    tags = {(doc, section): 'S' + str(i) for i, (doc, section, _, _) in enumerate(sections, 1)}
    concepts = {c['id']: {**c, 'source_tag': tags.get((c['document_id'], c['section_id']), '?')}
                for c in payload['concepts']}
    graph, positions = unified_positions(concepts, payload['statements'])
    legend = [Patch(facecolor=color, edgecolor='#536579', label=k.replace('_', ' ').title())
              for k, color in COLORS.items() if any(k in c['kinds'] for c in concepts.values())]
    xs, ys = zip(*positions.values())
    width = 34
    height = max(20, width * (max(ys) - min(ys) + 5) / (max(xs) - min(xs) + 5))
    fig, ax = plt.subplots(figsize=(width, height))
    draw(ax, payload['statements'], concepts, positions)
    ax.set_aspect('equal')
    fig.suptitle('Maintenance knowledge graph', fontsize=25, y=.99)
    fig.text(.5, .975, f"{len(concepts)} concepts · {len(payload['statements'])} source-supported statements · "
             'one graph, with disconnected components preserved', ha='center', fontsize=13)
    fig.legend(handles=legend, loc='lower center', ncol=5, fontsize=12, frameon=False)
    fig.subplots_adjust(top=.95, bottom=.05, left=.025, right=.975)
    for ext in ('png', 'svg'):
        fig.savefig(target / ('knowledge_graph.' + ext), dpi=180, facecolor='white')
    with PdfPages(target / 'knowledge_graph.pdf') as pdf:
        pdf.savefig(fig)
        sourcefig = plt.figure(figsize=(14, 10))
        text = ['Source key — tags on graph nodes', '']
        for i, (_, _, document, section) in enumerate(sections, 1):
            text.extend(textwrap.wrap(f'S{i}: {document} — {section}', 100))
            text.append('')
        text.extend(['Distinct source-scoped concepts retain distinct IDs, even with matching names.',
                     'Arrow numbers refer to the evidence pages that follow. No new connections are inferred.',
                     'Colors show the first matching concept role in legend order. Technical approval remains pending.'])
        sourcefig.text(.05, .95, '\n'.join(text), va='top', fontsize=11, linespacing=1.5)
        pdf.savefig(sourcefig)
        plt.close(sourcefig)
        evidence_pages(pdf, 'Knowledge graph — source evidence', payload['statements'])
    plt.close(fig)
    write_json(target / 'manifest.json', {'plot_version': VERSION, 'ontology_digest': digest(payload),
        'concepts': len(concepts), 'statements': len(payload['statements']),
        'components': nx.number_weakly_connected_components(graph),
        'node_ids': sorted(positions), 'statement_ids': [s['id'] for s in payload['statements']],
        'source_key': [{'tag': tags[(d, s)], 'document': name, 'section': title}
                       for d, s, name, title in sections]})
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ontology', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    print(generate(args.ontology, args.output))
