# Data attribution and limitations

GlycoAhead uses the ShanghaiT2DM portion of the Shanghai diabetes dataset, version 5.

- Release: https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933/5
- DOI: https://doi.org/10.6084/m9.figshare.21600933.v5
- Original data descriptor: https://www.nature.com/articles/s41597-023-01940-7
- Release license: Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/

Attribute the release and its authors using Figshare's citation export when publishing. Code's MIT license does not replace the dataset's license. Raw files are excluded from Git by default. Importing converts source timestamps to ISO 8601 with an assumed Asia/Shanghai offset, retains numeric CGM values, excludes invalid/conflicting rows, and derives features and sensor-defined event labels. Original files are never modified.

The local import contains 100 independent T2DM IDs, 109 recordings and 112,462 retained glucose readings. Counts derive from imported files, not model performance. File and clinical-summary SHA-256 hashes are saved. The UI and canonical food fields are English. Nutrition catalog v3 uses the original Chinese line only to clarify ambiguous identities/preparations and explicitly reviewed portion transcription problems. Exact English/Chinese line pairs are hashed; original source text is preserved.

Clinical-summary age and diabetes duration are treated as available enrollment history. Their precise availability is not proven by the release. Undated laboratory measurements, BMI/weight, medication free text and the Hypoglycemia summary are excluded from predictive inputs. This is a deliberately small history stream. Extra clinical columns are not fabricated.

The Chinese cohort, recording context and therapies may differ from Indian ambulatory care. Replaying recordings cannot establish performance on a consumer device or a real clinical service. No external Indian validation or clinician review has occurred.

Other datasets discussed (AI-READI, CGMacros, DiaGame) are not imported or used by this implementation. Their permissions cannot be inferred from Shanghai's license.
# Nutrition reference extension

USDA FoodData Central FNDDS 2019-2020, October 2022 release: https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_json_2022-10-28.zip . Documentation: https://www.ars.usda.gov/ARSUserFiles/80400530/pdf/fndds/2019_2020_FNDDS_Doc.pdf . USDA government data are public-domain; retain attribution. Selected reference profiles, source identifiers and hashes are included in `backend/glycoahead/resources/nutrition-catalog-v1.json`. Generic aliases, selected product defaults and the grain-mixture recipe are project assumptions. Nutrition references are reference-food data, not additional patient observations or ground-truth patient nutrients.

## Nutrition catalog v3 (research estimates)

The versioned catalog is `backend/glycoahead/resources/nutrition-catalog-v3.json`. It supplies energy (kcal), carbohydrate, protein, fat and fibre (g), all per 100 g edible reference food. The source plan, selected source-record bundle and ingredient inventory are stored beside it. Every reference retains its URL, derivation, assumptions and quality flags. Recipe ingredient weights are allocated within one total dish weight; the entire dish weight is never applied to each ingredient.

Primary composition sources include [USDA FoodData Central](https://fdc.nal.usda.gov/data-documentation/), [Hong Kong CFS NIIS](https://www.cfs.gov.hk/english/nutrient/searchmenu.php), [PhilFCT](https://i.fnri.dost.gov.ph/fct/library/report/3640), [MEXT](https://fooddb.mext.go.jp/details/details.pl?ITEM_NO=2_02004_7) and [CREA](https://www.alimentinutrizione.it/tabelle-nutrizionali/006200). Shanghai borscht uses [this published recipe](https://thewoksoflife.com/red-vegetable-soup-shanghai-luo-song-tang/) with explicitly assumed edible yield. Other recipes use documented reference-food mixtures and project assumptions; they are not claimed to reproduce the patient's cooking. Manufacturer products are brand proxies. A few research-derived or low-confidence references are flagged separately, including Poria composition from a patent and peach gum represented by a whole-dessert proxy.

Licensing remains source-specific. USDA government records are public domain; CFS reference/personal noncommercial terms are **not** replaced by this project's MIT code license. Keep source attribution and review each source's redistribution terms before publishing the bundled non-USDA values. Raw downloaded pages and the patient database stay outside Git.

Preparation defaults follow the agreed policy: cooked grains/noodles, raw fruit/vegetable reference when preparation is unspecified, finished bread products, cooked animal foods and dairy/drinks as consumed. Explicit preparation is retained. Where a matching cooked composition is unavailable, a raw-composition proxy is flagged; moisture changes and nutrient retention are not measured. CFS insoluble-fibre values remain labelled lower bounds for total fibre. Trace/ND operational zeroes are labelled lower bounds, not measured zeroes. Missing source fields use only named proxies or documented compositional assumptions. Available carbohydrate is converted to approximate total carbohydrate by adding fibre where the source convention calls for it.

Full-cohort audit: 100 patients, 109 recordings, 9,509 food lines in 3,063 recorded meal cells. Estimates are available for 9,477 lines (99.66%) and 3,031 complete meals. The catalog contains 1,749 reference/recipe profiles and 703 estimated ingredient/preparation pairs out of 707. Four standalone ingredient pairs remain unresolved: Dendrobium, egg roll, fish intestines and notoginseng powder. Fish maw and shark fin have dry references with explicitly assumed rehydration; the recorded whole seafood dish uses a prepared-dish proxy. Coverage is not evidence of nutrient accuracy or predictive improvement.

The remaining 32 lines comprise herbal medicine (1), Dendrobium preparation (3), ambiguous egg roll (1), fasting notation (1), ambiguous fish intestines/sausage (4), assorted Japanese food (1), milk cereal with undosed notoginseng powder (16), unidentified orchid (1), Redoxon supplement (1), and unspecified snack/snacks (3). Their identity, formulation or dose cannot be recovered from these records. They remain missing, not zero. Incomplete meal totals remain null; known-item subtotals are retained separately. The audit includes patient, recording and event locations plus resolution reasons.

Rebuild offline and audit from the project directory in PowerShell:

```powershell
& '..\.venv\Scripts\python.exe' scripts/compile_nutrition_v3.py --source-bundle-only
& '..\.venv\Scripts\python.exe' scripts/audit_nutrition_v3.py
```

Import as a new immutable catalog (after a database backup):

```powershell
& '..\.venv\Scripts\python.exe' scripts/import_nutrition_v3.py
```

`data/nutrition-v3-audit.json`, `data/nutrition-v3-reproducibility.json` and `data/nutrition-v3-integration.json` record coverage, deterministic offline rebuilding and preservation checks. The SQLite tables are `nutrition_catalogs` (whole versioned catalog) and `nutrition_references` (individual profiles, values and provenance). Existing models/replays remain pinned to their original catalog. This update neither retrains nor activates a model and does not rewrite past prediction features. New model evaluation must assess uncertain-recipe sensitivity before any activation.

Subsequent model use, 18 October 2026: the user requested feeding this catalog into the model. Version `20261018T064051Z-6f7d0f` was retrained and activated for local research replay after meeting the existing validation targets. The catalog-import preservation statement above refers to the import operation. Recipe-sensitivity and external validation remain outstanding; the new model is a development demo, not a validated clinical release. See `docs/MODEL_CARD.md` for the measured trade-offs and preserved previous version.

