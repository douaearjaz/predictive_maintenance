# CWRU vibration features

`features.csv` contains 2,400 non-overlapping quarter-second segments from 60
recordings in the official **12 kHz drive-end bearing fault** table. Each segment
contains 3,000 samples from the drive-end channel. This is a first feature table,
not a trained diagnostic model. The ontology and raw recordings were not changed.

## Four features

Each segment has its mean removed, without amplitude normalization or filtering.
For the centered samples x:

- RMS = sqrt(mean(x²)): overall vibration magnitude.
- Peak-to-peak = max(x) − min(x): amplitude range.
- Kurtosis = mean(x⁴) / mean(x²)²: Pearson kurtosis, with Gaussian reference 3.
- Crest factor = max(abs(x)) / RMS: peak relative to overall magnitude.

Kurtosis and crest factor are blank if the centered signal is constant; they are
not replaced by zero. RMS and peak-to-peak retain the MAT amplitude units, without
claiming an independently verified physical-unit calibration. The other features
are dimensionless. These calculations do not define fault thresholds or probabilities.

## Files and provenance

- `catalogue.csv`: filenames, fault labels, defect sizes, positions, motor load and
  sampling rate from the official table; source and download URLs are included.
- `source_12k.html`: saved official table used to build the catalogue.
- `features.csv`: features plus recording/channel IDs, segment boundaries, speed
  when present in that channel's recording, and fault metadata.
- `manifest.json`: file hashes, selected/ignored channels, unused tail samples,
  and all exclusions. Incomplete trailing segments are discarded.

Source: https://engineering.case.edu/bearingdatacenter/12k-drive-end-bearing-fault-data

For files with multiple drive-end arrays, the channel matching the filename is
selected. When there is only one drive-end array, its actual key is retained even
if its internal number differs from the official filename. Missing RPM stays blank;
it is not replaced with approximate tabulated speed.

## Scope limitation

101 of the 161 downloaded files are outside this verified extraction subset.
Healthy baseline recordings are not included: their per-recording sampling rate
was not established from the official baseline page during this extraction. They
must be verified before inclusion in equal-duration segments. Other sampling-rate
and sensor-location groups are also excluded to keep this first extraction simple.
The current table supports exploration of defect types, not evaluation of healthy
versus defective diagnosis. Recorded defects do not automatically mean functional
bearing failure, nor establish their root causes such as poor lubrication.

## Evaluation and future mapping

Keep every segment from a recording in the same evaluation partition. The
`evaluation_group` also groups the same fault type, size and position across loads;
prefer holding those groups out together to reduce similarity leakage. Groups are
based on documented configuration, not a verified physical bearing serial number.
No train/test split is created yet. Do not feed identifiers or fault-label metadata
into a predictive feature matrix. Learn scaling, feature selection and fuzzy
thresholds from training data only.

Later, a separate mapping can connect vibration features to a bearing-condition
model. High RMS alone does not prove bearing damage or identify lubrication as its
cause. Fuzzy memberships and diagnostic probabilities have not been assigned.

## Reproduce

Dependencies are listed separately in `requirements-signals.txt`; NumPy and SciPy
were already available in the project environment. One extraction script:

```bash
myenv/bin/python -m src.reliable.cwru_features
myenv/bin/python -m unittest tests.test_cwru_features
```

The default command regenerates the derived CSV and manifest, preserving raw data.
