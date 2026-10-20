# Training-settings search

The `tune-settings` command searches eight fixed histogram-gradient-boosting configurations for the existing 54-feature model. The original configuration is one candidate. It varies learning rate, number of boosting iterations, maximum leaves, minimum examples per leaf and L2 regularization. Features, event labels, patient assignments and alert matching stay fixed.

Each outer run performs three inner folds using only its 60 training patients: 40 fit and 20 validate, with every training patient used for validation once. Preprocessing and patient weighting are fitted independently within each fold. Early stopping is disabled. Settings are selected by the highest mean patient-weighted average precision over the three folds, with lower raw Brier error breaking ties. This selection criterion measures probability ranking; it does not guarantee improved event recall at an alert threshold.

The selected configuration is refitted on all 60 patients, calibrated on the separate 10, assigned a threshold using the separate 10 threshold-selection patients, then evaluated on the original 20 evaluation patients. Each outer run selects its own configuration. A setting selected for one run must not be applied retrospectively to other runs and called independently selected, because patient roles overlap between runs.

The configuration recommendation for the existing deployment training group is the seed-2026 inner-CV winner. No common configuration is chosen from outer evaluation results. Best means best among these eight configurations by this selection criterion. This remains internal research on a cohort inspected during earlier development.

From the project directory in PowerShell:

```powershell
$env:OMP_NUM_THREADS = '4'
$env:OPENBLAS_NUM_THREADS = '4'
& '..\.venv\Scripts\python.exe' -m glycoahead.cli tune-settings --experiment 20261020T072646Z-0b27fa
```

The command copies the original comparison into a new artifact directory, preserving its model results. It verifies frozen source/window/model checksums, saves candidate definitions and exact inner folds before fitting, writes all candidate fold scores and three new final models, and publishes a new latest comparison only after completion. It never activates a tuned model. Trusted local joblib archives only.

## Completed search — 20 October 2026

Run `20261020T073241Z-982161` completed 72 inner-fold fits and three final fits. The report, all candidate scores, exact patient folds, fitted models, predictions and verification are saved under `artifacts/experiments/20261020T073241Z-982161/`. Model evidence now displays this comparison as “Current + settings tuned on training patients.”

For the existing deployment training group (seed 2026), the selected configuration is `learning_rate=0.05`, `max_iter=140`, `max_leaf_nodes=15`, `min_samples_leaf=80`, `l2_regularization=10`, `early_stopping=False`, `random_state=2026`. Compared with the original settings, only learning rate changes from 0.10 to 0.05. Its inner mean patient-weighted average precision was 0.533067 versus original 0.518103. The seed-2027 group independently selected the same configuration (inner AP 0.462561 versus original 0.446885).

Seed 2028 independently selected `learning_rate=0.05`, `max_iter=280`, `max_leaf_nodes=7`, `min_samples_leaf=160`, `l2_regularization=30`, with the same fixed early-stopping and random-seed settings. Its inner AP was 0.517528 versus original 0.487089. Thus the data does not identify one universally best setting. No common setting was selected from evaluation results.

Final episode recall for seeds 2026/2027/2028 was **82.65% / 82.19% / 76.95%**, compared with original **82.31% / 80.82% / 75.32%**. Respective false alerts/day were **1.391 / 0.848 / 0.997**, compared with **1.532 / 0.848 / 0.926**. The third split gained recall with more false alerts.

Unweighted means across the three independently selected models: **80.60% recall**, **1.079 false alerts/day**, **26.48-minute mean warning**, **0.047402 Brier error** and **0.480942 average precision**. Original means were **79.49%**, **1.102/day**, **27.05 minutes**, **0.047487** and **0.480885**. Median warnings remained 30/15/15 minutes, and mean fractions of caught episodes warned at least 30 minutes early were 46.85% versus original 47.05%. These are modest, mixed improvements; the average tuned recall remains below the simple baseline's 81.06%, with fewer false alerts and longer mean warning. Statistical significance and external generalization are not established. The 80.60% figure describes the tuning procedure with different settings per split, not one shared configuration.

Artifact verification passed: all 15 model hashes, unchanged original 12 results, exact outer splits/window checksum, no inner-fold patient leakage, selection matching the frozen ranking rule, regenerated evaluation metrics from saved predictions, and reloaded-model prediction agreement. Frontend type checking and production build passed. The active model pointer remains unchanged; the recommended configuration is a research candidate, not a silently deployed replacement.


## Explicit deployment — 20 October 2026

Following the user's request, the reviewed seed-2026 winner was registered as `tuned-20261020T073241Z-982161-seed2026` and activated for new replays. The earlier statement that the active pointer stayed unchanged describes the search itself. Deployment is a separate subsequent action. Threshold is 0.32; personalization remains disabled; the nutrition catalog and 75-minute cooldown are unchanged. A backup of the prior database and active pointer is retained locally.


## Meal-variant searches — 20 October 2026

Comparison `20261020T120637Z-34ecb1` extends the completed current-model search. It adds two feature specifications across all three original patient assignments: 144 inner fits and six final fits. All eight configurations and the ranking rule were fixed before the new evaluations. Search uses only each split's 60 training patients, followed by separate calibration, threshold selection and evaluation. No active model was changed by this run.

- Meal timing (72 features): mean recall **81.94%**, false alerts/day **1.0930**, mean warning **26.83 minutes**, Brier **0.047189**. Previously: 77.72%, 0.9979/day, 26.41 minutes, 0.047693. Higher recall comes with more false alerts.
- Pre-meal glucose (60 features): mean recall **79.84%**, false alerts/day **1.0115**, mean warning **26.51 minutes**, Brier **0.046932**. Previously: 78.78%, 1.0657/day, 27.06 minutes, 0.047328. Recall and false-alert burden improve while mean warning decreases.
- Current features (54 inputs): existing tuned results remain **80.60%**, **1.0788/day**, **26.48 minutes**. These results were preserved, not recomputed.

Both new specifications selected `conservative` for seeds 2026 and 2028 (learning rate 0.05, 280 iterations, 7 leaves, minimum 160 samples/leaf, L2 30); seed 2027 selected `shorter` (learning rate 0.05, 140 iterations, 15 leaves, minimum 80 samples/leaf, L2 10). Early stopping is false and estimator seed is 2026 throughout. Thresholds are chosen separately per model and split.

The interface replaces the original current, meal-timing and pre-meal-glucose rows with their tuned versions. The baseline remains visible. Original results and models remain in the experiment archive for audit; no historical metrics were overwritten. The full report contains both original and tuned results. The selected 54-feature model remains the model used for patient replay; the new 72/60-feature models are comparison models.

Reproduce from the completed original tuning archive:

```bash
python -m glycoahead.cli tune-meal-variants --experiment 20261020T073241Z-982161
```

On a new checkout, first recreate the earlier comparison and use its newly generated identifier. The packaged aggregate-only report is not a resumable training archive.
