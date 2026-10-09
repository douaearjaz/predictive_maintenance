"""Extract four time-domain features from the verified 12 kHz CWRU subset."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.io import loadmat


def features(signal):
    """Mean-centered RMS, peak-to-peak, Pearson kurtosis, crest factor."""
    x = np.asarray(signal, dtype=float).reshape(-1)
    if len(x) < 4 or not np.isfinite(x).all():
        raise ValueError('A segment must contain at least four finite samples')
    x = x - x.mean()
    variance = np.mean(x * x)
    rms = np.sqrt(variance)
    return {'rms': float(rms), 'peak_to_peak': float(np.ptp(x)),
            'kurtosis': float(np.mean(x ** 4) / variance ** 2) if variance > 0 else None,
            'crest_factor': float(np.max(np.abs(x)) / rms) if rms > 0 else None}


def extract(folder, catalogue, output, seconds=0.25):
    if not np.isfinite(seconds) or seconds <= 0:
        raise ValueError('Segment duration must be positive and finite')
    folder, output = Path(folder), Path(output)
    with Path(catalogue).open(newline='') as handle:
        metadata = list(csv.DictReader(handle))
    if len({m['filename'] for m in metadata}) != len(metadata):
        raise ValueError('Duplicate catalogue filenames')
    rows, recordings, skipped = [], [], []
    for meta in metadata:
        path = folder / meta['filename']
        if not path.exists():
            skipped.append({'filename': path.name, 'reason': 'catalogued_file_missing'})
            continue
        fs = int(meta['sample_rate_hz'])
        samples = int(round(seconds * fs))
        if samples < 4 or not np.isclose(samples, seconds * fs):
            raise ValueError('Duration must represent an integer number of at least four samples')
        data = loadmat(path)
        channels = [k for k in data if k.endswith('_DE_time')]
        expected = f'X{int(path.stem):03d}_DE_time'
        if expected in channels:
            channel = expected
        elif len(channels) == 1:
            channel = channels[0]  # Some official filenames differ from internal IDs.
        else:
            raise ValueError(f'{path.name}: ambiguous drive-end channel {channels}')
        array = np.asarray(data[channel])
        if array.ndim != 2 or 1 not in array.shape:
            raise ValueError(f'{path.name}: expected a vector')
        signal = array.reshape(-1)
        if not np.isfinite(signal).all():
            raise ValueError(f'{path.name}: nonfinite samples')
        rpm_key = channel.split('_')[0] + 'RPM'
        rpm = float(data[rpm_key].item()) if rpm_key in data else None
        recording = {**meta, 'recording_id': path.stem, 'channel': channel,
                     'rpm': rpm, 'samples': len(signal),
                     'segments': len(signal) // samples, 'discarded_tail_samples': len(signal) % samples,
                     'ignored_de_channels': [c for c in channels if c != channel],
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        recordings.append(recording)
        # Group all loads of the same fault type/size/location together for evaluation.
        group = '_'.join([meta['fault_label'],meta['fault_diameter_in'],meta['outer_race_position']])
        for i in range(len(signal) // samples):
            start = i * samples
            rows.append({'recording_id': path.stem, 'filename': path.name,
                'channel': channel, 'segment_index': i, 'start_sample': start,
                'end_sample_exclusive': start + samples, 'sample_rate_hz': fs,
                'duration_seconds': seconds, 'load_hp': meta['load_hp'], 'rpm': rpm,
                'fault_label': meta['fault_label'], 'fault_diameter_in': meta['fault_diameter_in'],
                'outer_race_position': meta['outer_race_position'], 'evaluation_group': group,
                **features(signal[start:start + samples])})
    if not rows:
        raise ValueError('No complete segments were extracted')
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'features.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    included = {r['filename'] for r in recordings}
    skipped.extend({'filename': p.name, 'reason': 'outside_verified_12k_subset'}
                   for p in sorted(folder.glob('*.mat')) if p.name not in included)
    manifest = {'recordings': recordings, 'excluded_files': skipped,
        'feature_rows': len(rows), 'window_seconds': seconds, 'overlap': 0,
        'preprocessing': 'subtract each segment mean; no scaling, filtering or resampling',
        'kurtosis_definition': 'Pearson fourth central moment / variance squared (Gaussian reference 3)',
        'amplitude_units': 'original MAT signal units; no unit conversion asserted',
        'undefined_features': 'blank for constant segments',
        'healthy_baseline_included': False,
        'limitation': 'Fault-only subset; not ready for healthy-versus-defective evaluation.',
        'split_policy': 'Keep recording IDs together; preferably hold out evaluation_group to separate matching defect configurations across loads.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return {'recordings': len(recordings), 'feature_rows': len(rows), 'excluded_files': len(skipped)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default='CWRU_dataset')
    p.add_argument('--catalogue', default='analysis/cwru_features/catalogue.csv')
    p.add_argument('--output', default='analysis/cwru_features')
    p.add_argument('--seconds', type=float, default=0.25)
    a = p.parse_args()
    print(json.dumps(extract(a.input, a.catalogue, a.output, a.seconds), indent=2))
