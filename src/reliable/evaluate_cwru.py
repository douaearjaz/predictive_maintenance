"""Evaluate CWRU features on held-out configurations and loads; no random window split."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, log_loss
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.naive_bayes import GaussianNB
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

FEATURES = ['rms', 'peak_to_peak', 'kurtosis', 'crest_factor']
LABELS = ['ball_defect', 'inner_race_defect', 'outer_race_defect']


def evaluate(source='analysis/cwru_features/features.csv', output='analysis/cwru_evaluation'):
    source, output = Path(source), Path(output)
    with source.open(newline='') as f:
        rows = list(csv.DictReader(f))
    x = np.array([[float(r[k]) for k in FEATURES] for r in rows])
    if not np.isfinite(x).all():
        raise ValueError('Missing/nonfinite features; review constant or invalid segments first')
    y = np.array([r['fault_label'] for r in rows])
    recording = np.array([r['recording_id'] for r in rows])
    if set(y) != set(LABELS):
        raise ValueError('This evaluation expects the three documented defect types')
    sets = {f: [i] for i, f in enumerate(FEATURES)}
    sets.update(rms_and_kurtosis=[0, 2], all_four=[0, 1, 2, 3])
    results, predictions, splits = [], [], []
    for protocol, field in [('unseen_defect_configuration', 'evaluation_group'), ('unseen_load', 'load_hp')]:
        groups = np.array([r[field] for r in rows])
        folds = list(LeaveOneGroupOut().split(x, y, groups))
        for train, test in folds:
            assert not set(recording[train]) & set(recording[test])
            assert not set(groups[train]) & set(groups[test])
            splits.append({'protocol': protocol, 'held_out_group': str(groups[test[0]]),
                           'train_recordings': sorted(set(recording[train])),
                           'test_recordings': sorted(set(recording[test]))})
        for name, cols in sets.items():
            for method in ['gaussian_naive_bayes', 'logistic_regression'] + (['random_forest_check'] if name == 'all_four' else []):
                probabilities = np.zeros((len(rows), len(LABELS)))
                majority_predictions = np.empty(len(rows), dtype=object)
                for train, test in folds:
                    if set(y[train]) != set(LABELS):
                        raise ValueError('A training fold is missing a defect class')
                    classifier = {'gaussian_naive_bayes': GaussianNB(),
                                  'logistic_regression': LogisticRegression(max_iter=2000),
                                  'random_forest_check': RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=1)}[method]
                    model = make_pipeline(StandardScaler(), classifier)
                    # Scaling and model fitting use training recordings only.
                    model.fit(x[train][:, cols], y[train])
                    probs = model.predict_proba(x[test][:, cols])
                    probabilities[test] = probs[:, [list(model.classes_).index(c) for c in LABELS]]
                    classes, counts = np.unique(y[train], return_counts=True)
                    majority_predictions[test] = classes[counts.argmax()]
                truth, probs, majority = [], [], []
                for rid in sorted(set(recording)):
                    indices = np.flatnonzero(recording == rid)
                    assert len(set(y[indices])) == 1
                    truth.append(y[indices[0]])
                    probs.append(probabilities[indices].mean(axis=0))
                    majority.append(majority_predictions[indices[0]])
                    if name == 'all_four':
                        predictions.append({'protocol': protocol, 'model': method,
                            'recording_id': rid, 'true_label': truth[-1],
                            'predicted_label': LABELS[int(np.argmax(probs[-1]))],
                            **{f'p_{c}':float(p) for c,p in zip(LABELS,probs[-1])}})
                probs = np.array(probs)
                predicted = np.array(LABELS)[probs.argmax(axis=1)]
                onehot = np.array([[int(c == t) for c in LABELS] for t in truth])
                results.append({'protocol': protocol, 'feature_set': name, 'model': method,
                    'recording_balanced_accuracy': float(balanced_accuracy_score(truth, predicted)),
                    'majority_balanced_accuracy': float(balanced_accuracy_score(truth, majority)),
                    'recording_log_loss': float(log_loss(truth, probs, labels=LABELS)),
                    'recording_multiclass_brier_sum': float(np.mean(np.sum((probs-onehot)**2,axis=1))),
                    'confusion_matrix': confusion_matrix(truth,predicted,labels=LABELS).tolist()})
    # Correlations of recording means, for descriptive redundancy assessment only.
    means = np.array([x[recording==r].mean(axis=0) for r in sorted(set(recording))])
    report = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'rows':len(rows), 'recordings':len(set(recording)), 'labels':LABELS,
        'features': FEATURES, 'recording_mean_correlation':np.corrcoef(means,rowvar=False).tolist(),
        'results': results, 'splits': splits,
        'limits': ['Only defective bearings: no normal/defective discrimination measured.',
            'Configuration groups are proxies, not verified physical bearing identities.',
            'Window probabilities are averaged per recording, not multiplied as independent evidence.',
            'No nested feature selection: comparisons are exploratory and not an untouched final test.',
            'No fuzzy membership functions or real-world probability calibration validated.',
            'Gaussian naive Bayes assumes features independent given defect type; check correlated features.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n')
    with (output/'recording_predictions.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(predictions[0]));writer.writeheader();writer.writerows(predictions)
    for r in results:
        print(r['protocol'],r['feature_set'],r['model'],round(r['recording_balanced_accuracy'],3),
              'log_loss',round(r['recording_log_loss'],3))
    print('Correlation:',np.round(np.corrcoef(means,rowvar=False),3).tolist())
    return report


if __name__ == '__main__':
    evaluate()
