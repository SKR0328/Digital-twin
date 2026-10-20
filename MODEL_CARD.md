# Model card — selected tuned release

## Identity and purpose

Version: `tuned-20261020T073241Z-982161-seed2026`. Research forecast of new sustained high-glucose episodes in recorded adult Type 2 diabetes CGM. Replay only; not a validated medical device.

Input schema: `cgm13-nutrition-v3`, 54 features. Thirteen contiguous 15-minute CGM readings plus derived statistics, age, diabetes duration, timestamped meals/medication entries and estimated nutrition. The exact ordered input list is stored in the model artifact. Nutrient assumptions and reference provenance remain embedded in the frozen catalog; its hash is `352c8a26aecc7e9331b5b6e086cb6ff5ff9f109fb2c6123bbcc681c2697e00e5`.

## Endpoint and eligibility

Two consecutive readings >180 mg/dL preceded by two readings <=180. Onset is the first high reading. Predict only while current and preceding readings are <=180. Onset horizon: +15/+30/+45/+60 minutes; label maturity: +75 minutes. Missing/noncontiguous input causes abstention. Incomplete future labels are censored.

## Model and selection

Median imputation with missingness indicators, scaling, histogram gradient boosting and separate sigmoid calibration. Learning rate 0.05, max iterations 140, max leaves 15, minimum samples/leaf 80, L2 regularization 10, early stopping false, random seed 2026. Patients receive equal total training weight.

Sixty training patients, ten calibration, ten threshold selection, twenty evaluation. All recordings for each patient stay together. Eight settings were compared in three inner folds within the sixty training patients; mean patient-weighted average precision selected the configuration, with raw Brier score as tie-breaker. The deployed model uses the seed-2026 winner, not the best-looking outer evaluation run.

Alert probability threshold: 0.32, selected on the ten threshold-selection patients. The existing 75-minute cooldown is retained. This is an engineering alert policy, not a validated clinical recommendation.

## Results

Selected model evaluation: 243/294 eligible events caught (82.65%); 1.3907 false alerts/monitored patient-day; 30-minute median and 27.78-minute mean warning among caught events; Brier 0.047183. Threshold-selection results: 124/140 events (88.57%), 0.9645 false alerts/day and 30-minute median warning. The evaluation false-alert target of <=1/day is not met.

Three independently tuned runs averaged 80.60% recall, 1.0788 false alerts/day, 26.48-minute mean warning and 0.047402 Brier. Settings differ in the third run. The simple baseline averaged 81.06% recall, 1.1712 false alerts/day and 24.67-minute mean warning. Improvements are mixed, not established as statistically significant. Median warning values across tuned runs were 30/15/15 minutes; their average is not a pooled median.

Evaluation uses an already inspected cohort. These results measure internal robustness and do not establish external generalization, clinical benefit or safety. Patients overlap between runs, so three runs are not three independent studies. The aggregate report retains all runs; the local research archive retains individual predictions and split provenance.

## Digital-twin status

Replay maintains an evolving patient-specific state. Earlier matured outcomes can update a bounded risk offset with spacing and cold-start safeguards. **Personalization is disabled for deployed alerts**: benefit has not been established for these tuned weights. The live product demonstrates updating state and population inference, not a validated personalized physiological simulation.

## Limitations

Chinese cohort, no Indian validation; 100 patients and short recordings; uncertain enrollment-history availability; undocumented meals/medicines; nutrient and generic-recipe estimates; no direct pharmacology or causal intervention model. Undated labs and outcome summaries are excluded. Clinical review, prospective evaluation and comprehensive sensor-noise testing remain outstanding.

## Reproduction and maintenance

Use the pinned dependencies and packaged artifact/checksum. The installer registers a version and uses its frozen nutrition catalog. New replays use the active version; old sessions retain their original version. No saved predictions are rewritten during activation. Only trusted joblib artifacts may be loaded.

See `TUNING.md` for the search protocol and `../README.md` for data import and startup.
