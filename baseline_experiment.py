"""Append a prespecified simple baseline using an immutable comparison's windows."""
from datetime import datetime, timezone
from hashlib import sha256
import gzip
import json
from pathlib import Path
import shutil
import uuid

import joblib

from .config import ARTIFACTS
from .domain import BASELINE_FEATURES
from .evaluation import choose_threshold
from .experiments import METRICS, report_for, summarize, write_json
from .training import fit_model


def compare_baseline(experiment):
    if Path(experiment).name != experiment or experiment in ('.', '..'):
        raise ValueError('Provide a local experiment identifier')
    parent = ARTIFACTS / 'experiments' / experiment
    if json.loads((parent / 'status.json').read_text())['state'] != 'completed':
        raise ValueError('Parent experiment must be completed')
    original = json.loads((parent / 'report.json').read_text())
    if any('trend_baseline' in run['models'] for run in original['runs']):
        raise ValueError('This experiment already contains the baseline; select its original parent')
    # Require unchanged fitting/scoring logic before comparing to saved model results.
    for name in ('training.py', 'evaluation.py', 'domain.py', 'ml.py', 'experiments.py'):
        expected = original['protocol']['source_sha256'][name]
        if sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'{name} changed since parent experiment; cannot silently reuse its results')
    archive = parent / 'windows.joblib'
    if sha256(archive.read_bytes()).hexdigest() != original['coverage']['windows_sha256']:
        raise ValueError('Parent window archive checksum mismatch')
    for run in original['runs']:
        for name, result in run['models'].items():
            if sha256((parent / str(run['seed']) / name / 'model.joblib').read_bytes()).hexdigest() != result['model_sha256']:
                raise ValueError('Parent model checksum mismatch')
    active_before = (ARTIFACTS / 'active.json').read_bytes()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    destination = parent.parent / run_id
    shutil.copytree(parent, destination)
    (destination / 'report.json').unlink()
    verification = destination / 'verification.json'
    if verification.exists():
        verification.unlink()
    protocol = original['protocol']
    protocol.update(run_id=run_id, parent_experiment=experiment,
                    parent_report_sha256=sha256((parent / 'report.json').read_bytes()).hexdigest())
    protocol['features']['trend_baseline'] = BASELINE_FEATURES
    protocol['baseline'] = {
        'algorithm': 'LogisticRegression(C=0.3, max_iter=1200, random_state=2026)',
        'inputs': 'Current glucose, 15min slope, 60min slope, sine/cosine of time of day',
        'preprocessing': 'Training-only median imputation with missing indicators and StandardScaler',
        'training': 'Equal total weight per patient; independent sigmoid calibration on the same calibration patients',
        'selection': 'No tuning: existing trend_baseline specification; original splits, windows, threshold grid, cooldown and scoring reused',
        'interpretation': 'Comparison changes both algorithm and input set; it does not isolate the incremental effect of food or history',
        'existing_models': 'Nine original fitted models/results copied unchanged; only three baseline models trained',
    }
    source = Path(__file__).read_bytes()
    (destination / 'baseline_experiment.py').write_bytes(source)
    protocol['baseline_source_sha256'] = sha256(source).hexdigest()
    write_json(destination / 'protocol.json', protocol)
    write_json(destination / 'status.json', {'state': 'loading_frozen_windows'})
    try:
        data = joblib.load(archive)  # Trusted local, checksum-verified archive only.
        rows, exposure = data['rows'], data['exposure']
        horizon = protocol['horizon_minutes']
        for run in original['runs']:
            seed = run['seed']
            subsets = {role: [r for r in rows if r['patient'] in ids] for role, ids in run['patients'].items()}
            if {role: len(v) for role, v in subsets.items()} != run['window_counts']:
                raise ValueError('Parent split/window counts do not match archived data')
            print(f'Seed {seed}: fitting 5-feature glucose/trend logistic baseline...', flush=True)
            write_json(destination / 'status.json', {'state': 'running', 'seed': seed, 'model': 'trend_baseline'})
            model = fit_model(subsets['train'], subsets['calibration'], BASELINE_FEATURES, boosting=False)
            threshold_rows = subsets['threshold']
            threshold_prob = model.predict([r['features'] for r in threshold_rows])
            threshold, _ = choose_threshold(threshold_rows, threshold_prob, horizon, exposure)
            evaluation_rows = subsets['evaluation']
            probabilities = model.predict([r['features'] for r in evaluation_rows])
            location = destination / str(seed) / 'trend_baseline'
            location.mkdir()
            joblib.dump(model, location / 'model.joblib')
            result = {'feature_count': len(BASELINE_FEATURES), 'threshold': threshold,
                      'threshold_group': report_for(threshold_rows, threshold_prob, threshold, horizon, exposure),
                      'evaluation': report_for(evaluation_rows, probabilities, threshold, horizon, exposure),
                      'model_sha256': sha256((location / 'model.joblib').read_bytes()).hexdigest()}
            write_json(location / 'metrics.json', result)
            with gzip.open(location / 'evaluation-predictions.jsonl.gz', 'wt', encoding='utf-8') as output:
                for row, probability in zip(evaluation_rows, probabilities):
                    output.write(json.dumps({k: row[k] for k in ('patient', 'recording', 'time', 'label', 'events')} |
                                            {'probability': float(probability)}) + '\n')
            run['models']['trend_baseline'] = result
            write_json(destination / f'run-{seed}.json', run)
            print(json.dumps({'seed': seed, **{key: result['evaluation'][key] for key in METRICS}}), flush=True)
        original['summary'] = summarize(original['runs'])
        original['active_model_unchanged'] = (ARTIFACTS / 'active.json').read_bytes() == active_before
        if not original['active_model_unchanged']:
            raise RuntimeError('Active model changed during comparison')
        write_json(destination / 'report.json', original)
        write_json(destination / 'status.json', {'state': 'completed', 'models_evaluated': 12, 'new_fits': 3})
        write_json(destination.parent / 'latest.json', {'run_id': run_id, 'report': str(destination / 'report.json')})
        print(f'Complete: {destination / "report.json"}', flush=True)
        return original
    except Exception as exc:
        write_json(destination / 'status.json', {'state': 'failed', 'error': str(exc)})
        raise
