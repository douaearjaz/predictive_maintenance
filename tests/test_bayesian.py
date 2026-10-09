import copy
import unittest
from src.reliable.bayesian import infer, validate


class BayesianTests(unittest.TestCase):
    def setUp(self):
        # Synthetic arithmetic fixture only; not motor probability estimates.
        self.model = {'nodes': {
            'fault': {'parents': [], 'p_present': [0.1]},
            'signal': {'parents': ['fault'], 'p_present': [0.2, 0.8]}}}

    def test_bayes_rule_and_prior(self):
        self.assertAlmostEqual(infer(self.model, 'fault')['p_present'], 0.1)
        result = infer(self.model, 'fault', {'signal': True})
        self.assertAlmostEqual(result['p_present'], 0.08 / 0.26)
        self.assertAlmostEqual(result['evidence_probability'], 0.26)

    def test_multiple_parents_row_order(self):
        model = {'nodes': {
            'a': {'parents': [], 'p_present': [0.5]},
            'b': {'parents': [], 'p_present': [0.5]},
            'c': {'parents': ['a', 'b'], 'p_present': [0.1, 0.2, 0.3, 0.4]}}}
        self.assertAlmostEqual(infer(model, 'c', {'a': True, 'b': False})['p_present'], 0.3)

    def test_missing_values_do_not_become_defaults(self):
        self.model['nodes']['fault']['p_present'] = [None]
        validate(self.model, require_probabilities=False)
        with self.assertRaises(ValueError):
            infer(self.model, 'fault')

    def test_cycle_bad_cpt_and_unknown_evidence(self):
        bad = copy.deepcopy(self.model)
        bad['nodes']['fault'] = {'parents': ['signal'], 'p_present': [0.1, 0.2]}
        with self.assertRaises(ValueError):
            validate(bad)
        for value in [float('nan'), -0.1, True]:
            bad = copy.deepcopy(self.model)
            bad['nodes']['fault']['p_present'] = [value]
            with self.assertRaises(ValueError):
                validate(bad)
        with self.assertRaises(ValueError):
            infer(self.model, 'fault', {'missing': True})

    def test_impossible_evidence_even_when_query_observed(self):
        self.model['nodes']['fault']['p_present'] = [0]
        with self.assertRaises(ValueError):
            infer(self.model, 'fault', {'fault': True})


if __name__ == '__main__':
    unittest.main()
