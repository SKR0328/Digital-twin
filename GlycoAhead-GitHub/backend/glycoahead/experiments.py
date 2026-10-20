"""Predeclared repeated patient splits; comparison only, no model activation."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
import gzip
import json
from pathlib import Path
import platform
import uuid

import joblib
import numpy as np
import sklearn
from sqlalchemy import select

from .config import ARTIFACTS
from .context import CONTEXT_FEATURES, CONTEXT_SCHEMA
from .db import Session, Recording, SourceReading, ContextEvent, ModelVersion
from .domain import FEATURES, add_minutes
from .evaluation import choose_threshold, full_report
from .meal_features import TEMPORAL_FEATURES, PREMEAL_FEATURES, FEATURE_SCHEMA, temporal_nutrient_features, premeal_glucose_features
from .ml import active_version, load_bundle
from .nutrition import NUTRITION_FEATURES, estimate_meal, catalog_digest
from .training import build_windows, fit_model

METRICS = ('event_recall', 'false_alerts_per_patient_day', 'median_lead_minutes',
           'mean_lead_minutes', 'caught_warned_30m_fraction', 'brier', 'average_precision')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def patient_splits(patients, seed):
    ids = sorted(set(patients))
    if len(ids) < 30:
        raise ValueError('At least 30 independent patients are required')
    np.random.default_rng(seed).shuffle(ids)
    n = len(ids)
    return {'train': ids[:int(n*.6)], 'calibration': ids[int(n*.6):int(n*.7)],
            'threshold': ids[int(n*.7):int(n*.8)], 'evaluation': ids[int(n*.8):]}


def report_for(rows, probabilities, threshold, horizon, exposure):
    report = full_report(rows, probabilities, threshold, horizon, exposure)
    leads = [v for p in report['patients'].values() for v in p['leads']]
    report['mean_lead_minutes'] = float(np.mean(leads)) if leads else None
    report['caught_warned_30m_fraction'] = sum(v >= 30 for v in leads) / len(leads) if leads else None
    return report


def summarize(runs):
    variants = list(runs[0]['models'])
    summary = {'models': {}, 'paired_differences': {},
               'aggregation': 'Unweighted mean and min/max across runs. Patients overlap between runs; these are descriptive ranges, not independent confidence intervals. Lead-time summaries average run summaries.'}
    for name in variants:
        summary['models'][name] = {}
        for metric in METRICS:
            values = [r['models'][name]['evaluation'][metric] for r in runs]
            known = [v for v in values if v is not None]
            summary['models'][name][metric] = {'values': values, 'mean': float(np.mean(known)) if known else None,
                'min': min(known) if known else None, 'max': max(known) if known else None}
        if name != 'current':
            summary['paired_differences'][name] = {metric: [
                r['models'][name]['evaluation'][metric] - r['models']['current']['evaluation'][metric]
                if r['models'][name]['evaluation'][metric] is not None and r['models']['current']['evaluation'][metric] is not None else None
                for r in runs] for metric in METRICS}
    return summary


def run_experiments(seeds=(2026, 2027, 2028), reference_version=None):
    seeds = tuple(seeds)
    if len(seeds) < 2 or len(set(seeds)) != len(seeds) or any(s < 0 for s in seeds):
        raise ValueError('Provide at least two distinct nonnegative split seeds')
    active_path = ARTIFACTS / 'active.json'
    active_before = active_path.read_bytes()
    reference_version = reference_version or active_version()
    with Session() as db:
        version = db.get(ModelVersion, reference_version)
        if version is None:
            raise ValueError('Reference model is not registered')
        bundle = load_bundle(version.path, version.sha256)
        catalog = bundle.metadata.get('nutrition_catalog')
        if not catalog:
            raise ValueError('Reference must embed a frozen nutrition catalog')
        columns = FEATURES + CONTEXT_FEATURES + NUTRITION_FEATURES
        if bundle.model.columns != columns:
            raise ValueError('Reference feature list differs from this comparison protocol')
        expected = {'max_iter': 140, 'max_leaf_nodes': 15, 'min_samples_leaf': 80,
                    'l2_regularization': 10, 'early_stopping': False, 'random_state': 2026}
        if any(bundle.model.estimator.named_steps['model'].get_params().get(k) != v for k, v in expected.items()):
            raise ValueError('Reference hyperparameters differ from the frozen fit_model template')
        records = db.scalars(select(Recording).order_by(Recording.id)).all()
        if any(r.audit.get('context_schema') != CONTEXT_SCHEMA for r in records):
            raise ValueError('Timestamped context has not been imported for every recording')
        readings, contexts = defaultdict(list), defaultdict(list)
        for r in db.scalars(select(SourceReading).order_by(SourceReading.recording_id, SourceReading.position)):
            readings[r.recording_id].append({'time': r.time, 'glucose': r.glucose})
        for e in db.scalars(select(ContextEvent).order_by(ContextEvent.recording_id, ContextEvent.time, ContextEvent.id)):
            contexts[e.recording_id].append({'time': e.time, 'kind': e.kind, 'payload': e.payload})
        model_hash = version.sha256
    horizon = bundle.horizon
    specs = {'current': columns, 'plus_meal_timing': columns + TEMPORAL_FEATURES,
             'plus_premeal_glucose': columns + PREMEAL_FEATURES}
    split_sets = {str(s): patient_splits([r.patient_id for r in records], s) for s in seeds}
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    directory = ARTIFACTS / 'experiments' / run_id
    directory.mkdir(parents=True)
    source_files = ('experiments.py', 'meal_features.py', 'training.py', 'evaluation.py',
                    'nutrition.py', 'nutrition_v3.py', 'context.py', 'domain.py', 'ml.py')
    source_dir = directory / 'source'; source_dir.mkdir()
    source_hashes = {}
    for name in source_files:
        data = (Path(__file__).parent / name).read_bytes()
        (source_dir / name).write_bytes(data); source_hashes[name] = sha256(data).hexdigest()
    protocol = {'schema': 'repeated-patient-comparison-v1', 'run_id': run_id,
        'scope': 'Internal robustness evaluation of a previously inspected cohort; not fresh independent validation.',
        'reference_version': reference_version, 'reference_model_sha256': model_hash,
        'nutrition_catalog_id': catalog_digest(catalog), 'horizon_minutes': horizon,
        'split_seeds': list(seeds), 'estimator_seed': 2026, 'patient_splits': split_sets,
        'features': specs, 'extra_feature_schema': FEATURE_SCHEMA,
        'fixed_hyperparameters': expected, 'calibration': 'Separate calibration patients, sigmoid, equal patient weight',
        'threshold_selection': 'Fixed 49-value grid; maximize threshold-group event recall under 1 false alert per monitored patient-day. Never select from evaluation results.',
        'alerts': f'Population probabilities only; {horizon+15}-minute cooldown. Personalization is not an experiment variable.',
        'inputs': 'Past observations only. Meal availability assumed equal to source event time. Same windows and exposure for all models.',
        'temporal_bins': '(lower, upper] minutes old, including age zero in bins starting at zero; missing/absent nutrients remain null.',
        'premeal_anchor': 'Last CGM strictly before the latest recorded meal in the preceding 4h; anchor must be at most 15min old. A 30min slope requires three contiguous readings. Reset at recording/gap boundary.',
        'deployment': 'No registration or activation of these evaluation models. Every split trains a fresh baseline and fresh feature variants.',
        'source_sha256': source_hashes,
        'data_provenance': [{'recording': r.id, 'patient': r.patient_id, 'source_sha256': r.source_sha256, 'summary_sha256': r.summary_sha256} for r in records],
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__},
        'limitations': ['All patients have appeared in earlier development or evaluation; reshuffling does not undo this.',
                       'Three overlapping splits are descriptive; do not select the best seed or treat runs as independent samples.',
                       'Nutrition and source-time availability are estimates/assumptions.',
                       'Delayed meal logs and external validation are not established by this run.']}
    write_json(directory / 'protocol.json', protocol)
    write_json(directory / 'nutrition-catalog.json', catalog)
    write_json(directory / 'status.json', {'state': 'building_features'})
    try:
        print(f'Experiment {run_id}: protocol frozen; building baseline windows...', flush=True)
        rows, exposure = build_windows(records, readings, horizon, contexts, catalog)
        @lru_cache(maxsize=12000)
        def cached_estimate(raw, alternate):
            return estimate_meal({'raw': raw, 'alternate_text': alternate}, catalog)
        def estimate(payload):
            return cached_estimate(payload['raw'], payload.get('alternate_text'))
        times = {k: [x['time'] for x in v] for k, v in readings.items()}
        event_times = {k: [x['time'] for x in v] for k, v in contexts.items()}
        for row in rows:
            key, at, since = row['recording'], row['time'], row['segment_start']
            ts = times[key]; end = bisect_right(ts, at)
            observed = readings[key][max(0, end-32):end]
            es = event_times.get(key, [])
            available = contexts[key][bisect_left(es, max(since, add_minutes(at, -240))):bisect_right(es, at)]
            row['features'].update(temporal_nutrient_features(available, at, since, catalog, estimate))
            row['features'].update(premeal_glucose_features(available, observed, at, since))
        archive = directory / 'windows.joblib'
        joblib.dump({'rows': rows, 'exposure': exposure}, archive, compress=3)
        coverage = {'eligible_labelled_windows': len(rows), 'source_readings': sum(len(v) for v in readings.values()),
                    'windows_sha256': sha256(archive.read_bytes()).hexdigest(),
                    'feature_nonmissing_fraction': {c: sum(r['features'].get(c) is not None for r in rows) / len(rows)
                                                    for c in TEMPORAL_FEATURES + PREMEAL_FEATURES},
                    'denominator_note': 'Eligible labelled windows/source readings is a reporting count ratio, not prospective uptime. Alert-day denominator includes nonforecastable observed time.'}
        write_json(directory / 'coverage.json', coverage)
        runs = []
        for seed in seeds:
            splits = split_sets[str(seed)]
            subsets = {k: [r for r in rows if r['patient'] in ids] for k, ids in splits.items()}
            if any(len({r['label'] for r in subset}) < 2 for subset in subsets.values()):
                raise ValueError(f'Seed {seed}: a split lacks both outcomes; report failure, do not replace seed')
            run = {'seed': seed, 'patients': splits, 'window_counts': {k: len(v) for k, v in subsets.items()}, 'models': {}}
            for name, cols in specs.items():
                print(f'Seed {seed}: fitting {name} ({len(cols)} features)...', flush=True)
                write_json(directory / 'status.json', {'state': 'running', 'seed': seed, 'model': name})
                model = fit_model(subsets['train'], subsets['calibration'], cols, boosting=True)
                threshold_rows = subsets['threshold']
                threshold_prob = model.predict([r['features'] for r in threshold_rows])
                threshold, _ = choose_threshold(threshold_rows, threshold_prob, horizon, exposure)
                evaluation_rows = subsets['evaluation']
                probabilities = model.predict([r['features'] for r in evaluation_rows])
                location = directory / str(seed) / name; location.mkdir(parents=True)
                joblib.dump(model, location / 'model.joblib')
                result = {'feature_count': len(cols), 'threshold': threshold,
                          'threshold_group': report_for(threshold_rows, threshold_prob, threshold, horizon, exposure),
                          'evaluation': report_for(evaluation_rows, probabilities, threshold, horizon, exposure),
                          'model_sha256': sha256((location / 'model.joblib').read_bytes()).hexdigest()}
                write_json(location / 'metrics.json', result)
                with gzip.open(location / 'evaluation-predictions.jsonl.gz', 'wt', encoding='utf-8') as f:
                    for row, probability in zip(evaluation_rows, probabilities):
                        f.write(json.dumps({k: row[k] for k in ('patient', 'recording', 'time', 'label', 'events')} |
                                           {'probability': float(probability)}) + '\n')
                run['models'][name] = result
                print(json.dumps({'seed': seed, 'model': name, **{k: result['evaluation'][k] for k in METRICS}}), flush=True)
            runs.append(run)
            write_json(directory / f'run-{seed}.json', run)
        summary = summarize(runs)
        report = {'protocol': protocol, 'coverage': coverage, 'runs': runs, 'summary': summary,
                  'active_model_unchanged': active_path.read_bytes() == active_before}
        if not report['active_model_unchanged']:
            raise RuntimeError('Active model changed during the experiment; inspect concurrent activity')
        write_json(directory / 'report.json', report)
        write_json(directory / 'status.json', {'state': 'completed', 'models_evaluated': len(runs)*len(specs)})
        write_json(ARTIFACTS / 'experiments' / 'latest.json', {'run_id': run_id, 'report': str(directory / 'report.json')})
        print(f'Complete: {directory / "report.json"}', flush=True)
        return report
    except Exception as exc:
        write_json(directory / 'status.json', {'state': 'failed', 'error': str(exc)})
        raise
