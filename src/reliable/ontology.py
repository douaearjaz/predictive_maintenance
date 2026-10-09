"""Small source-scoped ontology of reviewed claims; no inferred causal edges."""
import html
import json
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef
from src.io_utils import digest, write_json
from src.reliable.fmea import FAILURE_ALIASES, failure_name
from src.reliable.sections import now
from src.reliable.viewer import collect

VERSION = 'maintenance-ontology-v1'
NS = Namespace('https://example.org/maintenance/')
KINDS = {
    'component': 'Component', 'function': 'Function', 'failure_mode': 'FailureMode',
    'cause': 'Cause', 'effect': 'Effect', 'symptom': 'Symptom',
    'detection_method': 'DetectionMethod', 'maintenance_action': 'MaintenanceAction',
    'phenomenon': 'Phenomenon', 'unknown': 'UnclassifiedConcept',
}
RELATIONS = {
    'CAUSES': 'causes', 'LEADS_TO': 'leadsTo', 'HAS_SYMPTOM': 'hasSymptom',
    'DETECTED_BY': 'detectedBy', 'MITIGATED_BY': 'mitigatedBy',
    'HAS_FAILURE_MODE': 'hasFailureMode', 'HAS_FUNCTION': 'hasFunction',
    'AFFECTS': 'affects', 'ASSOCIATED_WITH': 'associatedWith',
}


def assemble(data, allow_assistant=False):
    concepts, statements, excluded = {}, [], []
    for c in data['statements']:
        review = c.get('review')
        reason = None
        if c.get('category') != 'statements':
            reason = 'not_a_statement'
        elif not review or review['decision'] != 'accepted':
            reason = 'not_accepted'
        elif review['reviewer_kind'] != 'human' and not allow_assistant:
            reason = 'human_review_required'
        elif not c['schema_valid'] or not c['evidence_valid'] or c['issues'] or c.get('duplicate_of'):
            reason = 'invalid_or_duplicate'
        if reason:
            excluded.append({'run_id': c['run_id'], 'candidate_id': c['candidate_id'], 'reason': reason})
            continue
        r = c['record']
        if r['relation'] not in RELATIONS:
            raise ValueError('Unknown relation: ' + r['relation'])
        endpoints = {}
        for side in ('subject', 'object'):
            endpoint = r[side]
            if endpoint['kind'] not in KINDS:
                raise ValueError('Unknown concept kind: ' + endpoint['kind'])
            label = failure_name(endpoint)
            # A repeated term joins chains within its section, not equipment across manuals.
            key = digest([c['document_id'], c['section_id'], label])[:24]
            concept = concepts.setdefault(key, {'id': key, 'label': label, 'kinds': [],
                'original_labels': [], 'document_id': c['document_id'], 'section_id': c['section_id']})
            for field, value in [('kinds', endpoint['kind']), ('original_labels', endpoint['text'])]:
                if value not in concept[field]:
                    concept[field].append(value)
            endpoints[side] = key
        statements.append({'id': digest([c['run_id'], c['candidate_id']])[:24], **endpoints,
            'relation': r['relation'], 'qualifier': r['qualifier'],
            'operating_conditions': r['operating_conditions'], 'evidence': c['resolved_evidence'],
            'original_record': r, 'review': review, 'run_id': c['run_id'],
            'candidate_id': c['candidate_id'], 'document_id': c['document_id'],
            'document_name': c['document_name'], 'section_id': c['section_id'],
            'section': c['section_title'], 'warnings': c.get('warnings', [])})
    for concept in concepts.values():
        concept['kinds'].sort()
        concept['original_labels'].sort()
    return {'generator_version': VERSION, 'namespace': str(NS),
            'status': 'draft', 'allow_assistant': allow_assistant, 'failure_aliases': FAILURE_ALIASES,
            'documents': data['documents'], 'concepts': sorted(concepts.values(), key=lambda x: x['id']),
            'statements': sorted(statements, key=lambda x: x['id']), 'excluded': excluded}


def graph_for(payload):
    g = Graph()
    g.bind('maint', NS)
    g.bind('owl', OWL)
    g.add((URIRef(str(NS)), RDF.type, OWL.Ontology))
    g.add((URIRef(str(NS)), OWL.versionInfo, Literal(VERSION)))
    g.add((URIRef(str(NS)), RDFS.comment, Literal(
        'Draft vocabulary and source-scoped concepts. Relations describe reviewed claims, '
        'not universal causal axioms. Qualifiers and conditions must be consulted.')))
    for name in ['Concept', 'EvidenceStatement', 'Evidence', *KINDS.values()]:
        g.add((NS[name], RDF.type, OWL.Class))
        g.add((NS[name], RDFS.label, Literal(name)))
    for name in KINDS.values():
        g.add((NS[name], RDFS.subClassOf, NS.Concept))
    for name in RELATIONS.values():
        g.add((NS[name], RDF.type, OWL.ObjectProperty))
        g.add((NS[name], RDFS.label, Literal(name)))
    g.add((NS.hasEvidence, RDF.type, OWL.ObjectProperty))
    for name in ['qualifier', 'conditionsJSON', 'reviewJSON', 'originalRecordJSON',
                 'documentId', 'sectionId', 'sourceJSON', 'quote', 'page', 'runId', 'candidateId']:
        g.add((NS[name], RDF.type, OWL.DatatypeProperty))
    for c in payload['concepts']:
        node = NS['concept/' + c['id']]
        for kind in c['kinds']:
            g.add((node, RDF.type, NS[KINDS[kind]]))
        g.add((node, RDFS.label, Literal(c['label'])))
        g.add((node, NS.documentId, Literal(c['document_id'])))
        g.add((node, NS.sectionId, Literal(c['section_id'])))
    for s in payload['statements']:
        node = NS['statement/' + s['id']]
        g.add((node, RDF.type, NS.EvidenceStatement))
        g.add((node, RDF.type, RDF.Statement))
        g.add((node, RDF.subject, NS['concept/' + s['subject']]))
        g.add((node, RDF.predicate, NS[RELATIONS[s['relation']]]))
        g.add((node, RDF.object, NS['concept/' + s['object']]))
        # Reification deliberately does not assert the unqualified subject-predicate-object triple.
        for name, value in [('qualifier', s['qualifier']), ('runId', s['run_id']),
                            ('candidateId', s['candidate_id'])]:
            g.add((node, NS[name], Literal(value)))
        for name, value in [('conditionsJSON', s['operating_conditions']),
                            ('reviewJSON', s['review']), ('originalRecordJSON', s['original_record'])]:
            if value is not None:
                g.add((node, NS[name], Literal(json.dumps(value, ensure_ascii=False, sort_keys=True))))
        for i, evidence in enumerate(s['evidence']):
            ev = NS['evidence/' + s['id'] + '/' + str(i)]
            g.add((node, NS.hasEvidence, ev))
            g.add((ev, RDF.type, NS.Evidence))
            g.add((ev, NS.sourceJSON, Literal(json.dumps(evidence, ensure_ascii=False, sort_keys=True))))
            for key in ('quote', 'page'):
                if key in evidence:
                    g.add((ev, NS[key], Literal(evidence[key])))
    return g


def readable_html(payload):
    esc = html.escape
    concepts = {c['id']: c for c in payload['concepts']}
    cards = []
    for s in payload['statements']:
        source = ''.join('<blockquote>' + esc(e.get('quote', e.get('original_quote', ''))) +
                         '</blockquote><small>Page ' + esc(str(e.get('page', '?'))) + '</small>'
                         for e in s['evidence'])
        condition = s['operating_conditions']
        cards.append('<article><h3>' + esc(concepts[s['subject']]['label']) + ' → ' +
            esc(s['relation'].lower().replace('_', ' ')) + ' → ' + esc(concepts[s['object']]['label']) +
            '</h3><p>Source qualifier: <strong>' + esc(s['qualifier']) + '</strong>' +
            (' · When: ' + esc(condition['text']) if condition else '') + '</p><p>' +
            esc(s['document_name']) + ' · ' + esc(s['section']) + '</p><details><summary>Source evidence</summary>' +
            source + '</details></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Maintenance ontology draft</title><style>body{font:17px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#183145;background:#f5f7fa}article{background:white;padding:18px;margin:16px 0;border:1px solid #ccd7df;border-radius:8px}h3{font-size:18px}input{padding:12px;width:90%;font:inherit}blockquote{border-left:3px solid #168478;padding-left:15px}a{color:#086b63}</style>
<h1>Maintenance ontology — first draft</h1><p>Selected passages from ''' + str(len({d['document_id'] for d in payload['documents']})) + ''' PDFs. Missing information stays unknown. Source checking does not replace technical approval.</p>
<p>Concept types: ''' + ', '.join(KINDS.values()) + '''. Each connection below is a source-supported statement; its qualifier and conditions remain part of its meaning.</p>
<p><a href="ontology.owl">OWL file</a> · <a href="ontology.ttl">Turtle file</a> · <a href="ontology.json">JSON with sources</a></p>
<p>''' + str(len(concepts)) + ' concepts · ' + str(len(cards)) + ''' statements</p><input id="search" aria-label="Search statements" placeholder="Search bearing, lubrication, a document…"><main>''' + ''.join(cards) + '''</main>
<script>document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('article').forEach(a=>a.hidden=!a.textContent.toLowerCase().includes(q))})</script></html>'''


def generate(roots, output='data/ontology', allow_assistant=False):
    payload = assemble(collect(roots), allow_assistant)
    folder = Path(output) / digest(payload)[:24]
    if (folder / 'manifest.json').exists():
        return folder
    graph = graph_for(payload)
    folder.mkdir(parents=True, exist_ok=True)
    graph.serialize(folder / 'ontology.ttl', format='turtle')
    graph.serialize(folder / 'ontology.owl', format='xml')
    # Verify both serializations before marking this export complete.
    from rdflib.compare import isomorphic
    for name, fmt in [('ontology.ttl', 'turtle'), ('ontology.owl', 'xml')]:
        if not isomorphic(graph, Graph().parse(folder / name, format=fmt)):
            raise ValueError('Ontology serialization did not round-trip: ' + name)
    write_json(folder / 'ontology.json', payload)
    (folder / 'index.html').write_text(readable_html(payload), encoding='utf-8')
    write_json(folder / 'manifest.json', {'created_at': now(), 'generator_version': VERSION,
        'input_digest': digest(payload), 'allow_assistant': allow_assistant,
        'concepts': len(payload['concepts']), 'statements': len(payload['statements']),
        'excluded': len(payload['excluded']), 'triples': len(graph), 'serialization_roundtrip': 'passed'})
    return folder
