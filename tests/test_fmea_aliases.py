import tempfile
import unittest
from unittest.mock import patch

from src.reliable.fmea import build
from src.reliable.viewer import field_html


class AliasTests(unittest.TestCase):
    def candidate(self, cid, subject, relation, obj, section='S', condition=None):
        return dict(candidate_id=cid, category='statements', section_id=section,
                    schema_valid=True, evidence_valid=True, issues=[],
                    resolved_evidence=[{'quote': 'Unchanged source quotation'}],
                    record=dict(subject={'text': subject[0], 'kind': subject[1]},
                                relation=relation, object={'text': obj[0], 'kind': obj[1]},
                                qualifier='may', operating_conditions=condition))

    def rows(self, records):
        decision = {'decision': 'accepted', 'reviewer_kind': 'human'}
        with tempfile.TemporaryDirectory() as folder, \
                patch('src.reliable.fmea.candidates', return_value=records), \
                patch('src.reliable.fmea.latest_review', return_value=decision):
            return build(folder)[1]['records']

    def pair(self, **kwargs):
        return [self.candidate('C', ('poor lubrication', 'cause'), 'CAUSES',
                               ('bearing failure', 'failure_mode')),
                self.candidate('S', ('failed bearing', 'failure_mode'), 'HAS_SYMPTOM',
                               ('heat', 'symptom'), **kwargs)]

    def test_equivalent_failure_combines_preserving_evidence_and_wording(self):
        records = self.pair()
        rows = self.rows(records)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symptom'][0]['value'], 'heat')
        self.assertEqual(rows[0]['cause'][0]['qualifier'], 'may')
        self.assertEqual({x['original_value'] for x in rows[0]['failure_mode']},
                         {'bearing failure', 'failed bearing'})
        self.assertEqual(rows[0]['symptom'][0]['evidence'], records[1]['resolved_evidence'])
        self.assertEqual(records[1]['record']['subject']['text'], 'failed bearing')

    def test_different_sections_or_conditions_do_not_join(self):
        for kwargs in ({'section': 'OTHER'}, {'condition': {'text': 'under load'}}):
            rows = self.rows(self.pair(**kwargs))
            self.assertEqual(len(rows), 2)
            self.assertIsNone(next(r for r in rows if r['cause'])['symptom'])

    def test_distinct_damage_and_wrong_role_do_not_join(self):
        for text, kind in [('damaged bearing', 'failure_mode'), ('bearing wear', 'failure_mode'),
                           ('failed bearing', 'phenomenon')]:
            records = self.pair()
            records[1]['record']['subject'] = {'text': text, 'kind': kind}
            rows = self.rows(records)
            self.assertIsNone(next(r for r in rows if r['cause'])['symptom'])

    def test_viewer_does_not_hide_distinct_conditions(self):
        fields = [dict(value='heat', qualifier='may', operating_conditions={'text': condition})
                  for condition in ('under load', 'at rest')]
        rendered = field_html(fields)
        self.assertIn('under load', rendered)
        self.assertIn('at rest', rendered)
