import copy
import unittest

from rdflib import RDF, Literal
from src.reliable.ontology import assemble, graph_for, readable_html, NS


class OntologyTests(unittest.TestCase):
    def fixture(self):
        return {'documents': [], 'statements': [{
            'category': 'statements', 'candidate_id': 'A', 'run_id': 'R',
            'document_id': 'D', 'document_name': 'source.pdf', 'section_id': 'S', 'section_title': 'Bearing',
            'schema_valid': True, 'evidence_valid': True, 'issues': [],
            'review': {'decision': 'accepted', 'reviewer_kind': 'assistant'},
            'resolved_evidence': [{'quote': '<Heat> may damage insulation.', 'page': 2}],
            'record': {'subject': {'text': '<Heat>', 'kind': 'phenomenon'},
                       'relation': 'CAUSES', 'object': {'text': 'insulation damage', 'kind': 'failure_mode'},
                       'qualifier': 'may', 'operating_conditions': {'text': 'under load'}}}]}

    def test_review_gate_and_invalid_exclusion(self):
        data = self.fixture()
        self.assertFalse(assemble(data)['statements'])
        self.assertEqual(len(assemble(data, True)['statements']), 1)
        for change in ({'evidence_valid': False}, {'duplicate_of': 'B'},
                       {'review': {'decision': 'uncertain', 'reviewer_kind': 'human'}}):
            bad = copy.deepcopy(data)
            bad['statements'][0].update(change)
            self.assertFalse(assemble(bad, True)['statements'])

    def test_qualified_claim_is_not_an_unconditional_edge(self):
        payload = assemble(self.fixture(), True)
        graph = graph_for(payload)
        claim = next(graph.subjects(RDF.type, NS.EvidenceStatement))
        subject = graph.value(claim, RDF.subject)
        target = graph.value(claim, RDF.object)
        self.assertNotIn((subject, NS.causes, target), graph)
        self.assertEqual(graph.value(claim, NS.qualifier), Literal('may'))
        self.assertIn('under load', str(graph.value(claim, NS.conditionsJSON)))
        ev = graph.value(claim, NS.hasEvidence)
        self.assertEqual(graph.value(ev, NS.quote), Literal('<Heat> may damage insulation.'))

    def test_chain_joins_same_section_without_transitive_claim(self):
        data = self.fixture()
        next_statement = copy.deepcopy(data['statements'][0])
        next_statement['candidate_id'] = 'B'
        next_statement['record']['subject'] = {'text': 'insulation damage', 'kind': 'cause'}
        next_statement['record']['object'] = {'text': 'motor failure', 'kind': 'failure_mode'}
        data['statements'].append(next_statement)
        payload = assemble(data, True)
        self.assertEqual(len(payload['concepts']), 3)
        self.assertEqual(len(payload['statements']), 2)
        next_statement['section_id'] = 'OTHER'
        self.assertEqual(len(assemble(data, True)['concepts']), 4)

    def test_readable_export_escapes_source(self):
        content = readable_html(assemble(self.fixture(), True))
        self.assertIn('&lt;Heat&gt;', content)
        self.assertNotIn('<Heat>', content)
        self.assertNotIn('reviewer_kind', content)


if __name__ == '__main__':
    unittest.main()
