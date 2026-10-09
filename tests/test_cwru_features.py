import csv
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy.io import savemat
from src.reliable.cwru_features import features, extract


class FeatureTests(unittest.TestCase):
    def test_known_waveform_and_offset(self):
        x = np.tile([-1., 1.], 10)
        self.assertEqual(features(x), {'rms': 1., 'peak_to_peak': 2., 'kurtosis': 1., 'crest_factor': 1.})
        self.assertEqual(features(x), features(x + 10))

    def test_constant_and_invalid(self):
        self.assertIsNone(features(np.ones(10))['kurtosis'])
        self.assertIsNone(features(np.ones(10))['crest_factor'])
        with self.assertRaises(ValueError):
            features([1, 2, 3, float('nan')])

    def test_segments_channel_selection_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            savemat(root/'105.mat', {'X105_DE_time': np.arange(11.).reshape(-1, 1),
                                     'X999_DE_time': np.ones((11,1)), 'X105RPM': [[1797]]})
            meta = {'filename':'105.mat','sample_rate_hz':8,'fault_label':'inner_race_defect',
                    'fault_diameter_in':'.007','outer_race_position':'','load_hp':0}
            with (root/'catalogue.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=meta);w.writeheader();w.writerow(meta)
            result=extract(root,root/'catalogue.csv',root/'out',0.5)
            self.assertEqual(result['feature_rows'],2)
            with (root/'out/features.csv').open(newline='') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual([r['start_sample'] for r in rows],['0','4'])
            self.assertEqual([r['end_sample_exclusive'] for r in rows],['4','8'])
            m=json.loads((root/'out/manifest.json').read_text())
            self.assertEqual(m['recordings'][0]['discarded_tail_samples'],3)
            self.assertEqual(m['recordings'][0]['ignored_de_channels'],['X999_DE_time'])
            self.assertEqual(rows[0]['channel'],'X105_DE_time')


if __name__=='__main__':
    unittest.main()
