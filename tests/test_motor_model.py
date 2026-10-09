import json
import unittest
from pathlib import Path
from rdflib import RDF, OWL
from src.reliable.motor_model import assemble, rdf_graph, viewer, NS


class MotorModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = json.loads((root / 'data/ontology/8ec228b61bde801bf5424fb6/ontology.json').read_text())
        cls.model = assemble(cls.source)

    def test_claims_preserve_evidence_and_source_endpoints(self):
        originals = {s['id']: s for s in self.source['statements']}
        self.assertEqual(set(originals), {s['id'] for s in self.model['claims']})
        for s in self.model['claims']:
            old = originals[s['id']]
            for field in ['qualifier', 'operating_conditions', 'evidence', 'review', 'original_record']:
                self.assertEqual(s[field], old[field])
            self.assertEqual(s['source_subject'], old['subject'])
            self.assertEqual(s['source_object'], old['object'])

    def test_alignment_does_not_merge_damage_and_failure(self):
        nodes = {n['id']: n for n in self.model['nodes']}
        self.assertEqual(len(nodes['term_bearing_failure']['source_concepts']), 2)
        self.assertEqual(len(nodes['term_shaft_misalignment']['source_concepts']), 2)
        damage = [n for n in nodes.values() if n['label'] == 'damaged bearing']
        self.assertEqual(len(damage), 1)
        self.assertNotEqual(damage[0]['id'], 'term_bearing_failure')

    def test_organization_connects_nodes_without_new_causal_claims(self):
        adjacent = {n['id']: set() for n in self.model['nodes']}
        for e in self.model['organization']:
            self.assertNotIn(e['relation'], ['CAUSES', 'LEADS_TO', 'MITIGATED_BY'])
            adjacent[e['subject']].add(e['object'])
            adjacent[e['object']].add(e['subject'])
        reached, pending = set(), ['electric_motor']
        while pending:
            n = pending.pop()
            if n not in reached:
                reached.add(n)
                pending.extend(adjacent[n] - reached)
        self.assertEqual(reached, set(adjacent))
        self.assertEqual(self.model['excluded'], self.source['excluded'])

    def test_rdf_does_not_assert_unqualified_claims_or_identity(self):
        g = rdf_graph(self.model)
        self.assertFalse(list(g.triples((None, OWL.sameAs, None))))
        for c in self.model['claims']:
            self.assertNotIn((NS[c['subject']], NS[c['relation']], NS[c['object']]), g)
            self.assertIn((NS['claim_' + c['id']], RDF.type, RDF.Statement), g)

    def test_general_repair_guidance_retains_applicability(self):
        claims = [c for c in self.model['claims'] if c['section_id'].startswith('timken-')]
        self.assertTrue(claims)
        self.assertTrue(all(c['applicability'].endswith('applicability_pending') for c in claims))

    def test_viewer_escapes_embedded_data(self):
        model = assemble(self.source)
        model['nodes'][0]['label'] = '</script><script>alert(1)</script>'
        output = viewer(model)
        self.assertNotIn('</script><script>alert(1)', output)
        self.assertIn('\\u003c/script>', output)


if __name__ == '__main__':
    unittest.main()
