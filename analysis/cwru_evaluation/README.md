# CWRU feature evaluation

## Finding

The four features contain defect-type information under familiar configurations, but are not demonstrated sufficient for robust diagnosis on unseen defect configurations. They are candidate Bayesian observations, not validated diagnostic probabilities. Healthy-versus-defective performance remains unknown because the feature CSV contains only defects.

## Method

Evaluated all 2,400 windows from 60 recordings. Compared each feature alone, RMS with kurtosis, and all four. Gaussian naive Bayes is a small probabilistic baseline; logistic regression tests a different model; a fixed 100-tree random forest checks nonlinear separability. No hyperparameter search was performed.

Two leave-one-group-out protocols:

- Unseen defect configuration: hold out all recordings of a fault type/size/outer-race position across loads (15 folds). This tests a stronger change in condition.
- Unseen load: hold out one of four motor loads. Other loads of matching defect configurations remain in training, so this is easier and does not establish generalization to unseen bearings.

Scaling is fitted separately on each training fold. No recording crosses training/testing within a fold. Window probabilities are averaged per recording and all reported metrics weight recordings equally. They are not multiplied as independent observations. Group IDs represent documented configurations, not confirmed specimen IDs.

Balanced accuracy is the mean recall across the three defect types. Always predicting the majority class gives 33.3%. These are exploratory cross-validation comparisons; selecting features based on them requires a later independent evaluation.

## All four features

| Held-out condition | Model | Balanced accuracy | Log loss (lower is better) |
|---|---|---:|---:|
| unseen_defect_configuration | gaussian_naive_bayes | 8.9% | 5.806 |
| unseen_defect_configuration | logistic_regression | 11.9% | 3.690 |
| unseen_defect_configuration | random_forest_check | 36.3% | 12.905 |
| unseen_load | gaussian_naive_bayes | 52.4% | 0.853 |
| unseen_load | logistic_regression | 45.2% | 0.862 |
| unseen_load | random_forest_check | 100.0% | 0.082 |

The random forest result across loads is strong, but its poor configuration-held-out result and large log loss show that its confidence does not transfer reliably. The simpler models also struggle on new configurations. These tests do not prove that no classifier could improve, but they do not justify calling these features sufficient or deploying their probabilities.

## Feature comparisons

| Feature set | Configuration-held-out Gaussian NB | Configuration-held-out logistic |
|---|---:|---:|
| rms | 23.8% | 31.0% |
| peak_to_peak | 14.3% | 28.6% |
| kurtosis | 29.8% | 19.0% |
| crest_factor | 14.3% | 19.0% |
| rms_and_kurtosis | 4.8% | 19.0% |
| all_four | 8.9% | 11.9% |

RMS and peak-to-peak have recording-mean correlation 0.921; kurtosis and crest factor have 0.949. This suggests redundancy. These are marginal correlations, not a formal test of conditional independence given defect type. Do not assume four independent pieces of evidence in a Bayesian network.

## What this means for the ontology

See ../measurement_mapping/mapping.json. Measurements attach to the existing motor-bearing component as observations. The extracted features have no exact equivalent in the current ontology; they remain external measurement properties. A future validated defect-type result can retrieve context about bearing damage, with scope checks. It cannot establish lubricant deficiency, overheating or complete functional failure. Neither ontology facts nor motor_bn.json were modified.

## Next justified work

1. Verify healthy recording sampling rates and add comparable features before binary condition evaluation.
2. Examine failed configurations, then consider a small number of frequency/envelope features if defect localization is required. This is a proposed next experiment, not a promise of improvement.
3. Compare features and learn any fuzzy memberships using training groups only.
4. Validate probabilities and feature dependencies before integrating the small bearing model with the broader graph.

The current dataset cannot learn probabilities for every cause in the PDF ontology, nor supply operational failure prevalence from this selected laboratory collection.

## Reproduce

```bash
myenv/bin/python -m src.reliable.evaluate_cwru
myenv/bin/python -m src.reliable.map_cwru
```

Dependencies: requirements-evaluation.txt. Results: evaluation.json (scores, confusion matrices, split membership and input hash), recording_predictions.csv (out-of-fold recording probabilities). No model was deployed.
