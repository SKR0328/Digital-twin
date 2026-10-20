"""Finite, frozen hyperparameter search within each outer training-patient group."""
from datetime import datetime, timezone
from hashlib import sha256
import gzip
import json
from pathlib import Path
import shutil
import uuid

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import ARTIFACTS
from .evaluation import choose_threshold
from .experiments import METRICS, report_for, summarize, write_json
from .ml import CalibratedModel
from .training import patient_weights

# Fixed before any new evaluations; original settings included as control.
CANDIDATES = [
    dict(name='original', learning_rate=.1, max_iter=140, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=10),
    dict(name='slower', learning_rate=.05, max_iter=280, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=10),
    dict(name='shallow', learning_rate=.05, max_iter=280, max_leaf_nodes=7, min_samples_leaf=80, l2_regularization=10),
    dict(name='conservative', learning_rate=.05, max_iter=280, max_leaf_nodes=7, min_samples_leaf=160, l2_regularization=30),
    dict(name='larger', learning_rate=.05, max_iter=280, max_leaf_nodes=31, min_samples_leaf=80, l2_regularization=10),
    dict(name='strong_l2', learning_rate=.1, max_iter=140, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=30),
    dict(name='larger_leaves', learning_rate=.1, max_iter=140, max_leaf_nodes=15, min_samples_leaf=160, l2_regularization=10),
    dict(name='shorter', learning_rate=.05, max_iter=140, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=10),
]


def inner_folds(patients, seed):
    ids = sorted(set(patients))
    np.random.default_rng(seed + 10000).shuffle(ids)
    return [list(part) for part in np.array_split(ids, 3)]


def estimator(settings):
    params = {k: v for k, v in settings.items() if k != 'name'}
    return Pipeline([('impute', SimpleImputer(strategy='median', add_indicator=True)),
                     ('scale', StandardScaler()),
                     ('model', HistGradientBoostingClassifier(**params, early_stopping=False, random_state=2026))])


def matrix(rows, columns):
    return np.array([[row['features'].get(c) if row['features'].get(c) is not None else np.nan
                      for c in columns] for row in rows], dtype=float)


def tune_settings(experiment):
    if Path(experiment).name != experiment or experiment in ('.', '..'):
        raise ValueError('Provide a local experiment identifier')
    parent = ARTIFACTS / 'experiments' / experiment
    if json.loads((parent / 'status.json').read_text())['state'] != 'completed':
        raise ValueError('Parent experiment must be complete')
    report = json.loads((parent / 'report.json').read_text())
    if any('tuned_current' in r['models'] for r in report['runs']):
        raise ValueError('Select the original untuned comparison')
    for name in ('training.py', 'evaluation.py', 'domain.py', 'ml.py', 'experiments.py'):
        if sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != report['protocol']['source_sha256'][name]:
            raise ValueError(f'Frozen comparison code changed: {name}')
    archive = parent / 'windows.joblib'
    if sha256(archive.read_bytes()).hexdigest() != report['coverage']['windows_sha256']:
        raise ValueError('Window checksum mismatch')
    for run in report['runs']:
        for name, result in run['models'].items():
            if sha256((parent / str(run['seed']) / name / 'model.joblib').read_bytes()).hexdigest() != result['model_sha256']:
                raise ValueError('Parent model checksum mismatch')
    active_before = (ARTIFACTS / 'active.json').read_bytes()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    root = parent.parent / run_id
    shutil.copytree(parent, root)
    (root / 'report.json').unlink()
    if (root / 'verification.json').exists():
        (root / 'verification.json').unlink()
    columns = report['protocol']['features']['current']
    protocol = report['protocol']
    protocol.update(run_id=run_id, tuning_parent=experiment,
                    tuning_parent_report_sha256=sha256((parent / 'report.json').read_bytes()).hexdigest())
    protocol['features']['tuned_current'] = columns
    protocol['tuning'] = {
        'candidates': CANDIDATES,
        'folds': {str(r['seed']): inner_folds(r['patients']['train'], r['seed']) for r in report['runs']},
        'selection': 'Highest unweighted mean of three fold patient-weighted average precision scores; tie-break lower patient-weighted raw Brier error, then candidate order',
        'scope': 'Each outer split independently tunes on its own 60 training patients (40 fit / 20 inner validation per fold). Outer calibration/threshold/evaluation patients are excluded from search.',
        'budget': '8 candidates x 3 folds x 3 outer splits = 72 inner fits, plus 3 final fits. No adaptive expansion after viewing results.',
        'fixed': {'features': 54, 'early_stopping': False, 'random_state': 2026},
        'finalization': 'Refit selected candidate on all 60 training patients; calibrate on original 10, select threshold on original 10, evaluate original 20 once.',
        'recommendation': 'Seed 2026 inner-CV winner is the configuration recommendation for the existing deployment training cohort. Never choose a common setting using outer evaluation scores.',
        'limitations': 'Best means best among eight tested settings by this internal ranking. It is not a global optimum or external validation. AP selection need not improve event recall/false alerts.'}
    source = Path(__file__).read_bytes()
    (root / 'tuning.py').write_bytes(source)
    protocol['tuning_source_sha256'] = sha256(source).hexdigest()
    write_json(root / 'protocol.json', protocol)
    write_json(root / 'status.json', {'state': 'loading_frozen_windows'})
    try:
        data = joblib.load(archive)
        rows, exposure = data['rows'], data['exposure']
        horizon = protocol['horizon_minutes']
        tuning_results = {}
        for run in report['runs']:
            seed = run['seed']
            subsets = {role: [r for r in rows if r['patient'] in ids] for role, ids in run['patients'].items()}
            if {role: len(v) for role, v in subsets.items()} != run['window_counts']:
                raise ValueError('Split/window mismatch')
            folds = protocol['tuning']['folds'][str(seed)]
            fold_data = []
            for validation_ids in folds:
                training = [r for r in subsets['train'] if r['patient'] not in validation_ids]
                validation = [r for r in subsets['train'] if r['patient'] in validation_ids]
                if any(len({r['label'] for r in part}) != 2 for part in (training, validation)):
                    raise ValueError('Inner fold lacks both labels')
                fold_data.append((matrix(training, columns), np.array([r['label'] for r in training]), patient_weights(training),
                                  matrix(validation, columns), np.array([r['label'] for r in validation]), patient_weights(validation)))
            scores = []
            for settings in CANDIDATES:
                ap, brier = [], []
                for fold, (x, y, weights, vx, vy, vw) in enumerate(fold_data):
                    write_json(root / 'status.json', {'state': 'tuning', 'seed': seed, 'candidate': settings['name'], 'fold': fold + 1})
                    learner = estimator(settings)
                    learner.fit(x, y, model__sample_weight=weights)
                    probabilities = learner.predict_proba(vx)[:, 1]
                    ap.append(float(average_precision_score(vy, probabilities, sample_weight=vw)))
                    brier.append(float(brier_score_loss(vy, probabilities, sample_weight=vw)))
                result = {'settings': settings, 'fold_average_precision': ap, 'fold_raw_brier': brier,
                          'mean_average_precision': float(np.mean(ap)), 'mean_raw_brier': float(np.mean(brier))}
                scores.append(result)
                write_json(root / f'tuning-{seed}-progress.json', scores)
                print(json.dumps({'seed': seed, 'candidate': settings['name'], 'inner_ap': result['mean_average_precision']}), flush=True)
            winner = max(scores, key=lambda s: (s['mean_average_precision'], -s['mean_raw_brier']))
            tuning_results[str(seed)] = {'winner': winner, 'candidates': scores, 'validation_patient_folds': folds}
            write_json(root / f'tuning-{seed}.json', tuning_results[str(seed)])
            print(f"Seed {seed}: selected {winner['settings']['name']} from inner CV; fitting final model...", flush=True)
            learner = estimator(winner['settings'])
            learner.fit(matrix(subsets['train'], columns), np.array([r['label'] for r in subsets['train']]),
                        model__sample_weight=patient_weights(subsets['train']))
            model = CalibratedModel(learner, columns)
            model.calibrate([r['features'] for r in subsets['calibration']], np.array([r['label'] for r in subsets['calibration']]), patient_weights(subsets['calibration']))
            threshold_rows = subsets['threshold']
            tp = model.predict([r['features'] for r in threshold_rows])
            threshold, _ = choose_threshold(threshold_rows, tp, horizon, exposure)
            evaluation_rows = subsets['evaluation']
            probabilities = model.predict([r['features'] for r in evaluation_rows])
            location = root / str(seed) / 'tuned_current'
            location.mkdir()
            joblib.dump(model, location / 'model.joblib')
            result = {'feature_count': len(columns), 'threshold': threshold, 'selected_settings': winner['settings'],
                      'threshold_group': report_for(threshold_rows, tp, threshold, horizon, exposure),
                      'evaluation': report_for(evaluation_rows, probabilities, threshold, horizon, exposure),
                      'model_sha256': sha256((location / 'model.joblib').read_bytes()).hexdigest()}
            write_json(location / 'metrics.json', result)
            with gzip.open(location / 'evaluation-predictions.jsonl.gz', 'wt', encoding='utf-8') as output:
                for row, probability in zip(evaluation_rows, probabilities):
                    output.write(json.dumps({k: row[k] for k in ('patient', 'recording', 'time', 'label', 'events')} |
                                            {'probability': float(probability)}) + '\n')
            run['models']['tuned_current'] = result
            write_json(root / f'run-{seed}.json', run)
            print(json.dumps({'seed': seed, 'selected': winner['settings']['name'], **{k: result['evaluation'][k] for k in METRICS}}), flush=True)
        report['tuning_results'] = tuning_results
        report['recommended_settings'] = tuning_results['2026']['winner']['settings'] if '2026' in tuning_results else None
        report['summary'] = summarize(report['runs'])
        report['active_model_unchanged'] = (ARTIFACTS / 'active.json').read_bytes() == active_before
        if not report['active_model_unchanged']:
            raise RuntimeError('Active model changed during tuning')
        write_json(root / 'report.json', report)
        write_json(root / 'status.json', {'state': 'completed', 'models_evaluated': sum(len(r['models']) for r in report['runs']), 'new_inner_fits': 72, 'new_final_fits': 3})
        write_json(root.parent / 'latest.json', {'run_id': run_id, 'report': str(root / 'report.json')})
        print(f'Complete: {root / "report.json"}', flush=True)
        return report
    except Exception as exc:
        write_json(root / 'status.json', {'state': 'failed', 'error': str(exc)})
        raise
