"""Build an equipment-centered view without erasing source claim boundaries.

Run: python -m src.reliable.motor_model --source PATH --output DIRECTORY
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL
from rdflib.compare import isomorphic

NS = Namespace('https://example.org/motor-model/')
TOPICS = {
    'bearings': ('Bearings: failure and damage', ['fault-10', 'ac-unbalanced-load', 'timken-damage', 'timken-repair']),
    'alignment': ('Shaft and coupling alignment', ['fault-07']),
    'windings': ('Windings and insulation', ['ac-winding']),
    'moisture': ('Moisture effects', ['epri-moisture']),
    'power': ('Voltage imbalance', ['fault-02']),
    'starting': ('Starting and control', ['lincoln-hums', 'lincoln-controller', 'abb-start-fuses']),
    'stalling': ('Motor stalling', ['abb-stalls']),
}
# Explicit vocabulary alignments, not declarations that different equipment is identical.
ALIGNMENTS = {
    ('fault-10', 'bearing failure'): 'bearing_failure',
    ('ac-unbalanced-load', 'bearing failure'): 'bearing_failure',
    ('fault-10', 'shaft misalignment'): 'shaft_misalignment',
    ('fault-07', 'misalignment'): 'shaft_misalignment',
}
CANONICAL_LABELS = {'bearing_failure': 'Bearing failure', 'shaft_misalignment': 'Shaft misalignment'}


def assemble(source):
    topics = [{'id': 'topic_' + key, 'label': label, 'kinds': ['knowledge_topic'],
               'sections': sections} for key, (label, sections) in TOPICS.items()]
    section_topic = {s: t['id'] for t in topics for s in t['sections']}
    nodes = {'electric_motor': {'id': 'electric_motor', 'label': 'Electric motor',
             'kinds': ['equipment_type'], 'status': 'user_defined_scope'}}
    nodes.update({t['id']: t for t in topics})
    mapping = {}
    for c in source['concepts']:
        key = ALIGNMENTS.get((c['section_id'], c['label'].lower()))
        target = 'term_' + key if key else 'source_' + c['id']
        mapping[c['id']] = target
        node = nodes.setdefault(target, {'id': target, 'label': CANONICAL_LABELS.get(key, c['label']),
            'kinds': [], 'source_concepts': [], 'topics': [],
            'alignment_status': 'assistant_proposed_vocabulary_alignment' if key else 'source_scoped'})
        node['source_concepts'].append(copy.deepcopy(c))
        node['kinds'] = sorted(set(node['kinds'] + c['kinds']))
        topic = section_topic.get(c['section_id'], 'topic_other')
        if topic == 'topic_other' and topic not in nodes:
            nodes[topic] = {'id': topic, 'label': 'Other motor information', 'kinds': ['knowledge_topic']}
        node['topics'] = sorted(set(node['topics'] + [topic]))
    claims = []
    for s in source['statements']:
        claim = copy.deepcopy(s)
        claim.update(source_subject=s['subject'], source_object=s['object'],
                     subject=mapping[s['subject']], object=mapping[s['object']],
                     layer='source_claim', applicability='source_context_only',
                     topic=section_topic.get(s['section_id'], 'topic_other'))
        if s['section_id'].startswith('timken-'):
            claim['applicability'] = 'general_bearing_guidance_motor_applicability_pending'
        claims.append(claim)
    organization = []
    for node in list(nodes.values()):
        if 'knowledge_topic' in node['kinds']:
            organization.append({'subject': 'electric_motor', 'relation': 'HAS_KNOWLEDGE_TOPIC', 'object': node['id']})
        for topic in node.get('topics', []):
            organization.append({'subject': topic, 'relation': 'ORGANIZES_CONCEPT', 'object': node['id']})
    # These organize the equipment model. They are explicitly curated, not extracted.
    for component, label, topic, relation in [
        ('bearing', 'Motor bearing', 'bearings', 'HAS_COMPONENT'),
        ('winding', 'Motor winding', 'windings', 'HAS_COMPONENT'),
        ('shaft', 'Motor shaft', 'alignment', 'HAS_COMPONENT'),
        ('controller', 'Motor controller system', 'starting', 'HAS_ASSOCIATED_SYSTEM'),
    ]:
        key = 'equipment_' + component
        nodes[key] = {'id': key, 'label': label, 'kinds': ['component_type'],
                      'status': 'assistant_curated_structure_pending_domain_review'}
        organization.extend([{'subject': 'electric_motor', 'relation': relation, 'object': key},
                             {'subject': 'topic_' + topic, 'relation': 'ABOUT', 'object': key}])
    for i, edge in enumerate(organization):
        edge.update(id='organization_' + str(i), layer='organization',
                    status='curated_navigation_not_causal_evidence')
    return {'version': 'motor-model-v1', 'status': 'integrated_draft',
        'scope': 'Electric motor equipment type; not a single installed asset or universal applicability claim.',
        'nodes': list(nodes.values()), 'claims': claims, 'organization': organization,
        'source_documents': copy.deepcopy(source['documents']),
        'excluded': copy.deepcopy(source['excluded']),
        'limitations': ['Only accepted statements from the input snapshot are included.',
            'Vocabulary alignments retain original concept IDs and do not assert owl:sameAs.',
            'Structural and topic links are curated organization, never Bayesian dependencies.',
            'No causal shortcut, probability, or maintenance action is inferred.',
            'Damage, wear and functional failure remain distinct.',
            'Unreviewed candidates remain in the review queue, not accepted facts.']}


def rdf_graph(payload):
    g = Graph()
    g.bind('motor', NS)
    g.add((NS[''], RDF.type, OWL.Ontology))
    for kind in sorted({k for n in payload['nodes'] for k in n['kinds']}):
        g.add((NS[kind], RDF.type, OWL.Class))
    for node in payload['nodes']:
        u = NS[node['id']]
        g.add((u, RDFS.label, Literal(node['label'])))
        for kind in node['kinds']:
            g.add((u, RDF.type, NS[kind]))
        g.add((u, NS.metadataJSON, Literal(json.dumps(node, sort_keys=True))))
    for edge in payload['organization']:
        g.add((NS[edge['relation']], RDF.type, OWL.ObjectProperty))
        g.add((NS[edge['subject']], NS[edge['relation']], NS[edge['object']]))
        g.add((NS[edge['id']], NS.metadataJSON, Literal(json.dumps(edge, sort_keys=True))))
    for claim in payload['claims']:
        u = NS['claim_' + claim['id']]
        g.add((u, RDF.type, RDF.Statement))
        g.add((u, RDF.subject, NS[claim['subject']]))
        g.add((u, RDF.predicate, NS[claim['relation']]))
        g.add((u, RDF.object, NS[claim['object']]))
        g.add((NS[claim['relation']], RDF.type, OWL.ObjectProperty))
        g.add((u, NS.metadataJSON, Literal(json.dumps(claim, sort_keys=True))))
        g.add((u, NS.qualifier, Literal(claim['qualifier'])))
    return g


def viewer(payload):
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Electric motor knowledge model</title>
<style>body{font:16px system-ui;margin:24px;background:#f4f7fa;color:#183145}button,select,input{font:inherit;padding:8px;margin:4px}svg{width:100%;min-width:900px;background:white;border:1px solid #ccd7df}#canvas{overflow:auto}article{background:white;padding:16px;margin:12px 0;border-left:4px solid #168478}small{color:#516574}blockquote{border-left:2px solid #ccd7df;padding-left:12px}text{font:12px system-ui}#detail{padding:12px}a{color:#086b63}</style>
<h1>Electric motor — unified knowledge graph</h1>
<p>One equipment model, with source-specific claims. Dashed gray links organize knowledge; solid teal arrows show source claims. Select a topic or click a concept to inspect its evidence.</p>
<p><a href="motor_model.json">JSON</a> · <a href="motor_model.ttl">Turtle</a> · <a href="motor_model.owl">OWL</a> · <a href="review_queue.json">Review queue</a> · <a href="README.md">Scope and review notes</a></p>
<label>Topic <select id="topic"><option value="">All topics</option></select></label>
<label>Search <input id="search" placeholder="cause, symptom, action…"></label>
<button id="reset">Clear selection</button><p id="summary"></p>
<div id="canvas"><svg id="graph" role="img" aria-label="Electric motor semantic graph"></svg></div>
<div id="detail"></div><main id="claims"></main>
<script>const model=DATA;
const $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
const nodes=new Map(model.nodes.map(n=>[n.id,n]));let selected='';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const topics=model.nodes.filter(n=>n.kinds.includes('knowledge_topic'));
topics.forEach(t=>{const o=document.createElement('option');o.value=t.id;o.textContent=t.label;$('topic').append(o)});
function el(tag,attrs,text){let x=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,v));if(text)x.textContent=text;$('graph').append(x);return x}
function render(){const topic=$('topic').value,q=$('search').value.toLowerCase();
const claims=model.claims.filter(c=>(!topic||c.topic===topic)&&(!selected||c.subject===selected||c.object===selected)&&JSON.stringify([nodes.get(c.subject).label,nodes.get(c.object).label,c.relation,c.section]).toLowerCase().includes(q));
const shownTopics=topics.filter(t=>!topic||t.id===topic), positions=new Map([['electric_motor',[180,50]]]);let nextY=150;
shownTopics.forEach(t=>{let y=nextY;positions.set(t.id,[180,y]);let children=model.nodes.filter(n=>n.topics?.includes(t.id));children.forEach((n,j)=>{if(!positions.has(n.id))positions.set(n.id,[500+(j%4)*270,y+Math.floor(j/4)*68])});nextY+=Math.max(160,Math.ceil(children.length/4)*68+85);});
model.nodes.filter(n=>n.id.startsWith('equipment_')).forEach((n,i)=>positions.set(n.id,[480+i*270,50]));
$('graph').replaceChildren();$('graph').setAttribute('viewBox',`0 0 1550 ${Math.max(500,nextY)}`);
const defs=document.createElementNS(ns,'defs');defs.innerHTML='<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#168478"/></marker>';$('graph').append(defs);
function edge(e,claim){const a=positions.get(e.subject),b=positions.get(e.object);if(!a||!b)return;let line=el('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:claim?'#168478':'#a7b3bf','stroke-width':claim?2:1,'stroke-dasharray':claim?'':'4 4',...(claim?{'marker-end':'url(#arrow)'}:{})});let title=document.createElementNS(ns,'title');title.textContent=nodes.get(e.subject).label+' → '+e.relation+' → '+nodes.get(e.object).label;line.append(title)}
model.organization.forEach(e=>edge(e,false));claims.forEach(e=>edge(e,true));
positions.forEach(([x,y],id)=>{const n=nodes.get(id),g=el('g',{tabindex:0,role:'button','aria-label':n.label});const r=document.createElementNS(ns,'rect');Object.entries({x:x-113,y:y-23,width:226,height:46,rx:9,fill:id===selected?'#c3eee8':id==='electric_motor'?'#dbeafe':'#fff',stroke:'#54788b'}).forEach(([k,v])=>r.setAttribute(k,v));g.append(r);let label=document.createElementNS(ns,'text');label.setAttribute('x',x);label.setAttribute('y',y+4);label.setAttribute('text-anchor','middle');label.textContent=n.label.length>32?n.label.slice(0,30)+'…':n.label;g.append(label);let title=document.createElementNS(ns,'title');title.textContent=n.label;g.append(title);const choose=()=>{if(n.kinds.includes('knowledge_topic')){$('topic').value=id;selected=''}else if(n.source_concepts){selected=selected===id?'':id}else{selected=''}render()};g.onclick=choose;g.onkeydown=e=>{if(e.key==='Enter')choose()};});
$('summary').textContent=`${model.claims.length} source claims in the model · ${claims.length} shown. Assistant-reviewed draft; equipment applicability still requires review.`;
$('detail').textContent=selected?nodes.get(selected).label+' — '+nodes.get(selected).kinds.join(', '):'Damage, failure, causes, symptoms, checks and maintenance actions retain their source roles.';
$('claims').innerHTML=claims.map(c=>`<article><h3>${esc(nodes.get(c.subject).label)} → ${esc(c.relation)} → ${esc(nodes.get(c.object).label)}</h3><p>${esc(c.document_name)} · ${esc(c.section)} · qualifier: ${esc(c.qualifier)}</p><p>Conditions: ${esc(c.operating_conditions?.text||'Not specified by this statement')} · Applicability: ${esc(c.applicability)}</p><small>Review: ${esc(c.review?.reviewer_kind)} · ${esc(c.review?.decision)}</small><details><summary>Source evidence and original wording</summary>${c.evidence.map(e=>`<blockquote>${esc(e.source_paragraph_cleaned||e.quote)}</blockquote><small>Page ${esc(e.page)}</small>`).join('')}<pre>${esc(JSON.stringify(c.original_record,null,2))}</pre></details></article>`).join('')||'<p>No accepted claims match this selection. Missing information remains unknown.</p>';
}
$('topic').onchange=()=>{selected='';render()};$('search').oninput=render;$('reset').onclick=()=>{selected='';$('search').value='';$('topic').value='';render()};render();
</script></html>'''.replace('DATA', data)


def generate(source_path, output, queue_path=None):
    raw = Path(source_path).read_bytes()
    source = json.loads(raw)
    payload = assemble(source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def write(name, obj):
        (output / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    write('motor_model.json', payload)
    graph = rdf_graph(payload)
    for name, fmt in [('motor_model.ttl', 'turtle'), ('motor_model.owl', 'xml')]:
        graph.serialize(output / name, format=fmt)
        assert isomorphic(graph, Graph().parse(output / name, format=fmt))
    (output / 'index.html').write_text(viewer(payload))
    queue = json.loads(Path(queue_path).read_text()) if queue_path else source['excluded']
    write('review_queue.json', queue)
    manifest = {'source': str(source_path), 'source_sha256': hashlib.sha256(raw).hexdigest(),
        'nodes': len(payload['nodes']), 'source_claims': len(payload['claims']),
        'organization_links': len(payload['organization']), 'queued_candidates': len(queue),
        'rdf_roundtrip': 'passed', 'status': 'draft_not_bayesian_network'}
    write('manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--queue')
    args = parser.parse_args()
    print(json.dumps(generate(args.source, args.output, args.queue), indent=2))
