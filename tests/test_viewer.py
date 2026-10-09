import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.io_utils import read_json, write_json
from src.reliable.documents import parse_selection
from src.reliable.viewer import generate, field_html, LABELS
from src.reliable.pipeline import extract, candidates, review
from src.reliable.fmea import build
from src.reliable.sections import clean_with_map


class ViewerTests(unittest.TestCase):
    def test_all_inspected_profiles_preserve_exact_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            for profile in read_json('config/document_profiles.json')['documents']:
                path, batch = parse_selection(profile['pdf'], profile, folder)
                self.assertEqual(len(batch['sections']), 3)
                self.assertTrue(batch['excluded_blocks'])
                for section in batch['sections']:
                    for p in section['paragraphs']:
                        self.assertEqual(clean_with_map(p['original_text']), (p['cleaned_text'], p['clean_to_original']))
                self.assertEqual(parse_selection(profile['pdf'], profile, folder)[0], path)
            bad = copy.deepcopy(profile)
            bad['sections'][0]['include'] = ['not an actual PDF heading or paragraph']
            with self.assertRaisesRegex(ValueError, 'matched 0 blocks'):
                parse_selection(profile['pdf'], bad, folder)

    def test_viewer_escapes_source_and_exports_qualifiers(self):
        row = {k: None for k in LABELS}
        field = {'value': '=1+1 </script><img src=x onerror=alert(1)>', 'qualifier': 'may',
                 'operating_conditions': {'text': 'only when rotating'}, 'evidence': []}
        row.update(failure_mode=[field], statement_ids=[], reviews=[], fmea_record_id='F1', run_id='R1',
                   document_id='D1', document_name='test.pdf', section_title='Fault', status_label='Assistant source check')
        data = {'created_at': '2026-09-15T00:00:00Z', 'documents': [], 'rows': [row], 'statements': []}
        with tempfile.TemporaryDirectory() as folder, patch('src.reliable.viewer.collect', return_value=data):
            path = generate([], folder)
            content = path.read_text()
            self.assertIn('&lt;/script&gt;&lt;img',content)
            self.assertNotIn('<img src=x',content)
            self.assertIn('When: only when rotating',content)
            self.assertIn('data-open="fmea-0"',content)
            self.assertIn('<dialog id="fmea-0"',content)
            with (Path(folder)/'fmea.csv').open(encoding='utf-8-sig',newline='') as stream:
                exported = next(csv.DictReader(stream))
            self.assertTrue(exported['failure_mode'].startswith("'="))
            self.assertIn('may',exported['failure_mode_qualifiers'])
            self.assertIn('only when rotating',exported['failure_mode_conditions'])
            self.assertEqual(read_json(Path(folder)/'fmea.json')['records'][0]['failure_mode'][0]['value'],field['value'])

    def test_unknown_field_does_not_become_an_instruction(self):
        self.assertIn('Not stated',field_html(None))
        self.assertNotIn('None',field_html(None))

    def test_remedy_is_attached_only_to_its_cause(self):
        text='Blown fuses can cause failure to start. Overload can cause failure to start. Blown fuses are addressed by replacing fuses.'
        cleaned,mapping=clean_with_map(text)
        section={'document_id':'D','document_name':'fixture.pdf','section_id':'S','section':'Starting', 'pages':[1], 'issues':[],
                 'paragraphs':[{'paragraph_id':'P','page':1,'bbox':[0,0,100,100],'original_text':text,'cleaned_text':cleaned,'clean_to_original':mapping,'issues':[]}]}
        def item(subject, relation, target, target_kind,quote):
            return {'subject':{'text':subject,'kind':'cause'},'relation':relation,'object':{'text':target,'kind':target_kind},
                    'qualifier':'asserted','operating_conditions':None,'evidence':[{'paragraph_id':'P','quote':quote}], 'needs_context_review':False,'review_note':''}
        records=[item('Blown fuses','CAUSES','failure to start','failure_mode','Blown fuses can cause failure to start.'),
                 item('Overload','CAUSES','failure to start','failure_mode','Overload can cause failure to start.'),
                 item('Blown fuses','MITIGATED_BY','replacing fuses','maintenance_action','Blown fuses are addressed by replacing fuses.')]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            batch=root/'batch.json'
            write_json(batch,{'batch_id':'B','parser_version':'fixture','segmentation_version':'fixture','cleaning_version':'fixture','pymupdf_version':'fixture','sections':[section]})
            run=extract(batch,root/'runs',source_kind='test_fixture', complete=lambda *args:{'content':json.dumps({'statements':records,'mentions':[],'ambiguities':[]}), 'finish_reason':'stop'})
            self.assertEqual(build(run)[1]['records'],[])
            for c in candidates(run): review(run,c['candidate_id'],'accepted','unit-test','Checked fixture')
            rows=build(run)[1]['records']
            self.assertEqual(len(rows),2)
            by_cause={r['cause'][0]['value']:r for r in rows}
            self.assertIsNone(by_cause['Overload']['maintenance_action'])
            self.assertEqual(by_cause['Blown fuses']['maintenance_action'][0]['value'],'replacing fuses')


if __name__=='__main__': unittest.main()
