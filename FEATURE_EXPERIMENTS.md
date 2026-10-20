# Repeated patient-split feature comparison

This experiment measures whether feature additions help across different patient assignments. It is internal robustness evaluation on the existing ShanghaiT2DM cohort. The cohort has already been inspected during development; these results are not a fresh independent test.

## Fixed experiment

Split seeds are **2026, 2027, 2028**, chosen before the run. Each assigns the same 100 unique patients to 60 training, 10 probability-calibration, 10 alert-threshold-selection and 20 evaluation patients. All recordings belonging to a patient remain together within a run. Each run trains fresh models; a fitted model from another split is never reused. Report every seed, including poor results.

Three feature sets are compared on identical windows and assignments:

- Current model specification: 54 glucose, historical, context and nutrition features.
- Current specification plus 18 meal-timing features: carbohydrate in 0–60, 60–120 and 120–180 minute bins; fat/protein in 0–120 and 120–240 minute bins; meal counts and item coverage for each distinct bin; time since the latest complete meal within four hours.
- Current specification plus six pre-meal features: last pre-meal glucose, 30-minute pre-meal slope, observed glucose change since the meal, time since the meal, baseline reading age and baseline availability.

Nutrient bins are `(lower, upper]` minutes old, with age zero included in bins starting at zero. Empty or incomplete bins have missing nutrient totals. A documented zero nutrient value remains zero. Counts indicate recording presence, not proof that an unrecorded meal did not occur. Explicit missing-meal markers and the note “Fasting for medical examination” do not count as meals in the new features.

The pre-meal anchor is strictly earlier than the latest recorded meal within four hours and at most 15 minutes before it. Its slope requires three contiguous CGM observations spanning 30 minutes. Changes since eating use only readings already observed at prediction time. No feature crosses a recording or CGM-gap reset. These are continuous warning features, not predictions of a planned meal before eating.

The baseline algorithm, hyperparameters and nutrition catalog are frozen from the reference model. Estimator random seed remains 2026; only patient assignments change. Every model uses its own calibration fit and alert threshold, chosen without evaluation patients. The existing threshold rule maximizes episode recall under one false alert per monitored patient-day on the threshold group. Evaluation may exceed that burden. Personalization is disabled across all three groups to isolate feature differences.

## Run

From the `glycoahead` directory in PowerShell:

```powershell
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
& '..\.venv\Scripts\python.exe' -m glycoahead.cli compare-features --seeds 2026 2027 2028 --reference-version 20261018T064051Z-6f7d0f
```

The command creates a new directory under `artifacts/experiments/`. It saves the protocol and exact patient assignments before training. It writes all model results and predictions, and never registers or activates its fitted evaluation models.

- `protocol.json`: configuration, catalog ID, source code hashes, patient assignments and original-data hashes.
- `source/`: copies of the Python modules used for the experiment.
- `nutrition-catalog.json`: exact frozen nutrition lookup.
- `windows.joblib`: shared features, labels, event times and exposure, for reproduction. Load only locally trusted artifacts.
- `coverage.json`: feature availability and eligible-window counts.
- `<seed>/<variant>/`: fitted model, metrics and compressed evaluation predictions.
- `run-<seed>.json`: all comparisons for one split.
- `report.json`: every run, descriptive means/ranges and paired differences.
- `status.json`: completed or failed state; a failed seed is never silently replaced.
- `artifacts/experiments/latest.json`: pointer written only after completion.

Report episode recall, false alerts/day, median and mean warning, fraction of caught episodes warned at least 30 minutes early, Brier error and average precision. Patient bootstrap intervals are calculated within each run. Across-run ranges are descriptive because patients overlap between runs; they are not confidence intervals for independent repetitions. Do not choose the best seed as the final performance claim.

The active app model remains a separate frozen artifact. Improved results here justify further development, not automatic deployment or clinical claims. Simulated delayed meal logs, external validation and a clinical review remain separate work.

## Checks

`python -m unittest discover -s tests -v` checks patient separation and reproducibility, time-bin boundaries, incomplete/absent versus true-zero nutrition, future-data exclusion, pre-meal anchor freshness, CGM discontinuity and agreement between full-archive and observed-prefix feature calls. CI runs this narrow behavioral suite alongside compilation and frontend building. It does not establish full application or clinical reliability.

## Simple baseline comparison — 20 October 2026

Run `20261020T072646Z-0b27fa` extends the completed 19 October comparison. It preserves all nine original model artifacts and results and adds three fresh baseline fits on the exact archived windows and original patient assignments. It is now the latest report displayed in Model evidence. The parent remains unchanged.

The baseline uses logistic regression with fixed `C=0.3`, `max_iter=1200`, seed 2026 and five inputs: current glucose, 15-minute slope, 60-minute slope, and sine/cosine of time of day. This is the existing simple baseline specification. Imputation/scaling are fitted only on training patients; weighting, sigmoid calibration, threshold-selection rule and 75-minute alert cooldown match the parent protocol. No settings were selected from these new evaluation results. This compares complete predictors, changing both algorithm and input set; it does not isolate the causal or incremental contribution of food features.

Across seeds 2026/2027/2028, baseline recall was **80.61% / 79.45% / 83.12%**, versus current **82.31% / 80.82% / 75.32%**. The baseline average was **81.06% recall**, **1.171 false alerts/patient-day**, and **24.67-minute mean warning**. Current averages remain **79.49%**, **1.102/day**, and **27.05 minutes**. Baseline median warning was 15 minutes in every run; current medians were 30/15/15 minutes. Fractions of caught episodes warned at least 30 minutes early averaged 44.17% for baseline and 47.05% for current.

Current had lower Brier error in all three runs (mean 0.04749 versus baseline 0.05152), and higher average precision in all three (mean 0.48088 versus 0.40965). At their separately selected thresholds, current recall was higher in two runs and lower in the third; its false alerts were lower in two runs and higher in the first. The evidence supports a tradeoff: no consistent overall superiority has been established. These results do not establish the added value of food/history specifically, statistical significance, or performance in India. Active app model selection remains separate.

Verification confirmed exact patient assignments and window identities, unchanged original results, all 12 model checksums, the archived window checksum, and unchanged active-model pointer. The frontend production build passed. Report and verification are under `artifacts/experiments/20261020T072646Z-0b27fa/`.

Reproduce this extension from the original completed parent in PowerShell:

```powershell
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
& '..\.venv\Scripts\python.exe' -m glycoahead.cli compare-baseline --experiment 20261019T150240Z-809d31
```

The extension verifies source and input checksums, trains the three baseline models and writes a new completed report. It never activates those models. Load only trusted local joblib archives.

## Completed comparison — 19 October 2026

The Model evidence page displays the latest completed comparison in its own research section, including across-run averages/ranges and expandable results for every seed. `/api/experiments/latest` serves that report; `/api/evaluation` continues to serve the active model's evaluation. Restart the backend after installing this update, then refresh the browser.

Run `20261019T150240Z-809d31` completed all nine fits using 87,985 eligible labelled windows from 112,462 source readings. The full results are in `artifacts/experiments/20261019T150240Z-809d31/report.json`; exact assignments, predictions, model artifacts and verification results are alongside it. The earlier partial run `20261019T145614Z-32e902` was superseded to exclude an explicit fasting note from the new meal features. The replacement retained the same seeds and model specifications; the partial results are not included in these summaries.

Unweighted averages across the three runs:

- Current 54-feature specification: **79.49% episode recall**, **1.102 false alerts/patient-day**, **27.05-minute mean warning**. Recall ranged from 75.32% to 82.31%; false alerts ranged from 0.848 to 1.532/day.
- Plus 18 meal-timing features: **77.72% recall**, **0.998 false alerts/patient-day**, **26.41-minute mean warning**. Recall ranged from 76.30% to 78.63%; false alerts ranged from 0.909 to 1.113/day.
- Plus six pre-meal glucose features: **78.78% recall**, **1.066 false alerts/patient-day**, **27.06-minute mean warning**. Recall ranged from 72.40% to 83.67%; false alerts ranged from 0.833 to 1.500/day.

In seed order 2026/2027/2028, median warning times were 30/15/15 minutes for current, 15/30/15 for meal timing, and 30/30/15 for pre-meal glucose. Across-run mean fractions of caught episodes warned at least 30 minutes early were 47.05%, 45.89% and 47.93%, respectively. These are run summaries, not pooled independent patient estimates.

**Decision: retain the active model.** Meal timing reduced false alerts on average, but only on one of the three paired runs, and reduced recall on two runs. Pre-meal features slightly reduced Brier probability error on all three runs (mean 0.047328 versus 0.047487), but did not consistently improve alert usefulness. Neither is a demonstrated overall replacement. No statistical significance or external-validation claim is made, and the two additions together were not evaluated.

Pre-meal glucose was available in 38.15% of eligible windows. Other windows may have no recent documented meal; this figure is not a nutrient-catalog failure rate. Missing features remain missing and are handled by the training pipeline.

Ten behavioral tests passed locally. Saved-artifact verification confirmed all nine fits, patient-role separation, source/window/model hashes, unchanged active model `20261018T064051Z-6f7d0f`, and reproduction of its original threshold-group results by the seed-2026 baseline. The new features remain research-only; they have not been added to app inference or historical prediction rows.
