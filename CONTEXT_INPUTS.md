# Meal, medication and patient context

The `cgm13-context-v2` candidate adds recorded context to the original 24 CGM/history features. It is a supervised event classifier, not a treatment simulator.

## Data flow

Original workbook cells → immutable `context_events` table (recording, row/column key, timestamp, raw text, parsed fields) → chronological replay/training window → shared `context_features` function → calibrated model → saved prediction features and source event IDs.

Events on rows with missing CGM are retained. Events are only eligible after the source-row timestamp, within the current uninterrupted CGM segment. Training and inference use the same rules. This replay assumes each context entry was available at its source-row time; actual documentation time is not independently verified. An eventual live connector must use both event time and received time, and cannot retroactively change a saved prediction.

## Candidate features

- Meal entries in the preceding three hours; time since a recorded meal (six-hour maximum); simple English text flags for starch/fruit; explicitly documented food grams and fluid mL. Total food mass is **not** carbohydrate mass. Partial/missing amounts remain unknown. English is primary; the Chinese cell is preserved as alternate source text and is not counted twice.
- Subcutaneous insulin entries, time since an entry, and explicitly documented IU over six hours. These amounts do not model formulation-specific activity or insulin on board.
- Non-insulin medication entries over six hours, including recorded metformin and sulfonylurea names. The source column also contains injectable agents; it is deliberately not called “oral medication.” Other names/doses remain available as raw text for review. Different drugs' mg doses are not summed.
- CSII bolus, CSII basal-rate and IV-insulin entry counts are separate. A basal-rate entry is not a delivered dose. Embedded repeated headers are rejected. No dosing or causal drug-effect claims are made.

Zero entry counts mean **no entries recorded**, not no intake or treatment. Amount/recency features are missing when not documented. Record completeness is not established.

Age and diabetes duration retain the original enrollment-availability assumption. BMI, smoking, alcohol, comorbidities, vascular complications and summary medication regimen are preserved as **undated display context**, not primary prospective predictors. Undated labs and outcome summaries remain excluded. Sleep, exercise, stress and genetic markers are not invented.

## Candidate workflow

```
glycoahead import-shanghai D:\diabetes_datasets --summary PATH_TO_ORIGINAL_SUMMARY
glycoahead train --context --development-only
```

Use the original summary with the hash matching the previous import; a translated workbook is a different source artifact. Reimport is idempotent and enriches existing unchanged recordings without deleting replay sessions or altering old prediction features.

Development-only training uses the established patient train/calibration/validation groups and withholds test metrics. It does not activate its model. The already inspected initial test set cannot be described as a fresh untouched test for later iterations. Compare candidate and original models on the same development patients; inspect false alerts, recall, calibration and recording completeness before final evaluation and activation. Feature presence alone does not establish a benefit.

The UI shows only context entries already released by the replay clock, plus clearly marked undated clinical context. It explicitly reports whether the pinned model actually uses context features. Existing v1 models and sessions remain compatible.

## First development result — 9 October

Candidate `20261009T151524Z-45e227`, 60-minute horizon, 39 inputs (24 original plus 15 context features). Imported 8,389 context entries across 109 recordings: 3,808 meals, 828 subcutaneous insulin entries, 2,171 non-insulin medication entries, 555 CSII bolus entries, 1,018 CSII basal-rate entries and nine IV entries. One embedded column-header cell was excluded. Source summary recovered from the original published ZIP matched the original import hash; the current translated summary workbook has a different hash and was not substituted.

On the same ten validation patients, the original combined model had 87.1% episode recall, 0.993 false alerts per monitored patient-day, 30-minute median warning, and Brier 0.04843. The context candidate had 85.7% recall, 0.965 false alerts per day, 15-minute median warning, and Brier 0.04704. Their validation-selected thresholds differ (0.28 versus 0.30), so this is not a comparison at exactly equal alert burden. These are **development results**, not fresh test evidence or achieved clinical outcomes.

The candidate missed the proposed warning-time target; candidate personalization also exceeded the proposed one-false-alert-per-day target. Context has not established an overall benefit, and the initial model remains active. The next modeling decision must be made using development data, with particular attention to medication/formulation representation, meal documentation and fair matched-alert-burden comparisons. No test metrics were computed in this candidate run.

The frontend production build completed. Automated tests and browser inspection were not run in this change.
