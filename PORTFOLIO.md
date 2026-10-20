# Portfolio and interview notes

## Evidence in this repository

- A working local product with explicit frontend/backend boundaries.
- OpenAPI documentation and a linked SQL schema.
- Read-only source import, hashes and reproducible dataset lineage.
- Separate offline training and observed-data inference paths.
- Patient-grouped splits and honest reporting of an underperforming personalization candidate.
- Transactional replay, stale-data handling, idempotent acknowledgement and conflict responses.
- Saved features, state revisions, outcome maturation and versioned model activation.
- Locked dependencies, local startup, Docker definition, CI build definition and operating documentation.

Do not claim tests, cloud deployment, production usage or clinical validation that have not occurred. The GitHub workflow and Docker files are definitions; executing and reviewing them is separate evidence.

## Resume wording

Only use figures from the final frozen report and keep the research context visible.

- Built GlycoAhead, a local Type 2 diabetes research application using React, FastAPI and SQLite, integrating patient history with 112,462 CGM readings across 100 participants; implemented chronological replay, auditable predictions and versioned model artifacts.
- Developed patient-separated glucose episode forecasting and baseline comparisons using scikit-learn; evaluated [MODEL] on [N] held-out patients with [EVENT_RECALL] recall, [FALSE_ALERTS] false alerts per patient-day and [LEAD_TIME] median warning, documenting calibration and generalization limits.

## Questions to be prepared for

1. Why a modular monolith and SQLite? Explain the one-user workload and why the process lock requires one API worker.
2. Why not random train/test windows? Overlapping windows and repeated visits from one person would leak information across splits.
3. Why does a 60-minute horizon require 75 future minutes for evaluation? The second above-threshold reading confirms a possible onset at +60.
4. How do you stop future-data leakage? Archive versus observed stores, shared feature rules, mature outcomes and fixed patient splits.
5. What makes this personalized? An explicit bounded state updated using previously observable outcomes; explain why its activation gate failed.
6. Why did you keep history when sensor-only performed better? It implements the brief's fusion concept, but the evidence does not support claiming incremental benefit. The product exposes that result.
7. How do you recover from duplicate requests or a crash? Cursor conflict checks, one transaction per replay batch, uniqueness constraints and persisted state.
8. Why not use an LLM? This is a timed numerical event-prediction problem; a language model adds no demonstrated value here.
9. What changes for public deployment? Authentication, authorization, stronger limits, TLS, concurrent storage design and operational monitoring.
10. What remains before clinical use? External/prospective validation, clinician-reviewed endpoint and workflow, risk management and applicable regulatory review.
