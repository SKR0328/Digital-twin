"""Build the submission PDFs. Optional authoring dependency: reportlab."""
from pathlib import Path
from xml.sax.saxutils import escape
import json
import math
import shutil

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pdf"
DOCS = ROOT / "docs/submission"
META = json.loads((ROOT / "docs/submission.json").read_text(encoding="utf-8"))
W, H = 960, 540
INK, GREEN, MINT, PAPER, MUTED, LINE = map(HexColor, [
    "#153A32", "#267464", "#DAEACB", "#F6F8F3", "#53665E", "#D7E0D8"])


def text(c, value, x, y, width, size=17, color=INK, bold=False, limit=None):
    style = ParagraphStyle("text", fontName="Helvetica-Bold" if bold else "Helvetica",
                           fontSize=size, leading=size * 1.3, textColor=color)
    p = Paragraph(value, style)
    _, height = p.wrap(width, H)
    if limit and height > limit:
        raise ValueError(f"Text exceeds its box: {value[:70]} ({height} > {limit})")
    p.drawOn(c, x, H - y - height)
    return height


def base(c, title, number, kicker="GLYCOAHEAD / HAPPIEST HEALTH DIGITAL TWIN CHALLENGE 2026"):
    c.setFillColor(PAPER); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(GREEN); c.rect(0, H - 9, W, 9, fill=1, stroke=0)
    text(c, kicker, 40, 29, 880, 10, GREEN, True)
    text(c, title, 40, 55, 880, 30, INK, True, 80)
    c.setStrokeColor(LINE); c.line(40, 35, 920, 35)
    text(c, "Surajkumar Reddiar | Rajiv Gandhi Institute of Technology", 40, 514, 760, 9, MUTED)
    text(c, f"{number:02d}   /   20 OCT 2026", 794, 514, 126, 9, MUTED)


def box(c, x, y, w, h, title, body="", size=16, fill=white):
    c.setFillColor(fill); c.setStrokeColor(LINE)
    c.roundRect(x, H-y-h, w, h, 12, fill=1, stroke=1)
    text(c, title, x+16, y+14, w-32, 15, GREEN, True, 25)
    if body:
        text(c, body, x+16, y+40, w-32, size, INK, limit=h-47)


def arrow(c, x1, y1, x2, y2):
    c.setStrokeColor(GREEN); c.setFillColor(GREEN); c.setLineWidth(1.5)
    c.line(x1, H-y1, x2, H-y2)
    a = math.atan2(y2-y1, x2-x1)
    p = c.beginPath(); p.moveTo(x2, H-y2)
    for da in (-.5, .5):
        p.lineTo(x2-7*math.cos(a+da), H-(y2-7*math.sin(a+da)))
    p.close(); c.drawPath(p, fill=1, stroke=0)


def bullets(items):
    return "<br/><br/>".join("&#8226; " + escape(item) for item in items)


def columns(c, title, number, left_title, left, right_title, right, note=None):
    base(c, title, number)
    box(c, 40, 126, 428, 320, left_title, bullets(left), 17)
    box(c, 488, 126, 432, 320, right_title, bullets(right), 17, MINT)
    if note: text(c, note, 44, 462, 870, 12, MUTED, limit=36)
    c.showPage()


def architecture(c, number=1):
    base(c, "Architecture: one app, two execution paths", number)
    text(c, "OFFLINE TRAINING", 40, 110, 200, 11, GREEN, True)
    text(c, "CHRONOLOGICAL INFERENCE", 510, 110, 360, 11, GREEN, True)
    box(c, 40, 134, 190, 80, "Original files", "Linked history, CGM,<br/>meals and medicines", 12)
    box(c, 260, 134, 190, 80, "SQLite archive", "Validated recordings<br/>and source hashes", 12)
    arrow(c, 230, 174, 260, 174)
    box(c, 40, 244, 190, 90, "Patient-level splits", "60 fit / 10 calibrate<br/>10 threshold / 20 evaluate", 12)
    box(c, 260, 244, 190, 90, "Train and evaluate", "Inner training-only search<br/>Frozen reports + model", 12)
    arrow(c, 350, 214, 350, 228); arrow(c, 350, 228, 135, 228); arrow(c, 135, 228, 135, 244)
    arrow(c, 230, 289, 260, 289)
    box(c, 40, 365, 410, 102, "Model registry and artifact store",
        "Version + checksum + calibrated predictor + frozen catalog.<br/>Offline evaluation never exposes future labels to replay features.", 13, MINT)
    arrow(c, 355, 334, 355, 365)
    box(c, 510, 134, 190, 80, "Replay adapter", "Release archived readings<br/>only up to event time", 12)
    box(c, 730, 134, 190, 80, "Past-only features", "13 CGM readings + history<br/>and timestamped context", 12)
    arrow(c, 450, 174, 510, 174); arrow(c, 700, 174, 730, 174)
    box(c, 510, 244, 190, 90, "Frozen inference", "Calibrated probability<br/>Eligibility + cooldown", 12)
    box(c, 730, 244, 190, 90, "FastAPI + React", "Timeline, alerts, evidence<br/>and reference lookup", 12)
    arrow(c, 825, 214, 825, 228); arrow(c, 825, 228, 605, 228); arrow(c, 605, 228, 605, 244)
    arrow(c, 700, 289, 730, 289)
    arrow(c, 450, 404, 478, 404); arrow(c, 478, 404, 478, 289); arrow(c, 478, 289, 510, 289)
    box(c, 510, 365, 410, 102, "Observed data, prediction log and patient state",
        "SQLite transactions preserve features and model IDs.<br/>Mature outcomes update a bounded candidate state.<br/>Personalization is disabled for deployed alerts.", 12, MINT)
    arrow(c, 605, 334, 605, 365); arrow(c, 825, 334, 825, 365)
    text(c, "One local FastAPI worker serves the API and built UI. Training runs as a separate CLI job. No live wearable connection.", 40, 479, 880, 10, MUTED)
    c.showPage()


def state_architecture(c):
    base(c, "Data relationships and chronology safeguards", 2)
    box(c, 40, 135, 250, 125, "Patient -> Recording", "One person can have several recordings.<br/>All visits stay in one split within a run.", 13)
    box(c, 330, 135, 260, 125, "Recording -> Source data", "SourceReading + ContextEvent<br/>CGM and timestamped meals/medicines.", 13)
    box(c, 630, 135, 290, 125, "ModelVersion -> Replay", "Each replay pins one model.<br/>Later activation does not rewrite history.", 13)
    box(c, 40, 276, 250, 135, "Replay -> ObservedReading", "Only released readings enter features.<br/>Insufficient or broken history means<br/>no new prediction.", 13)
    box(c, 330, 276, 260, 135, "Replay -> Prediction -> Alert", "Save exact features, probabilities,<br/>model version and state snapshot.<br/>Alerts can be acknowledged.", 13)
    box(c, 630, 276, 290, 135, "Mature outcomes -> State", "Resolve complete outcomes at +75 min.<br/>Spaced updates; reset at gaps/visits.<br/>Global model weights stay frozen.", 13)
    text(c, "Additional stores: NutritionCatalog / NutritionReference preserve lookup provenance; AuditEvent records important operations. Patient state is stored with the replay and prediction snapshots.", 44, 424, 870, 15, MUTED, limit=64)
    c.showPage()


def result_slide(c):
    base(c, "Results: compare recall, alert burden and warning", 11)
    headers = ["Three-run mean", "Recall", "False alerts/day", "Mean warning"]
    x = [52, 475, 600, 780]
    for xpos, h in zip(x, headers): text(c, h, xpos, 136, 200, 13, GREEN, True)
    rows = [
        ("Tuned current (54 features)", "80.60%", "1.08", "26.48 min"),
        ("Tuned meal timing (72 features)", "81.94%", "1.09", "26.83 min"),
        ("Tuned pre-meal glucose (60 features)", "79.84%", "1.01", "26.51 min"),
        ("Simple glucose + trend baseline", "81.06%", "1.17", "24.67 min"),
    ]
    for i, row in enumerate(rows):
        y = 177+i*48
        c.setFillColor(MINT if i==0 else white); c.roundRect(40, H-y-39, 880, 39, 5, fill=1, stroke=0)
        for j, value in enumerate(row): text(c, value, x[j], y+9, 410 if j==0 else 130, 15, INK, j==0)
    text(c, "<b>Deployed seed-2026 model:</b> 243/294 events caught (82.65%); 1.39 false alerts/day; 30-minute median warning. This single-run result is different from the three-run mean.", 48, 388, 860, 16, limit=55)
    text(c, "Warning times concern caught episodes. Runs share patients. Previously inspected cohort: internal robustness, not external validation. Recall is not overall classification accuracy.", 48, 454, 860, 12, MUTED, limit=40)
    c.showPage()


def presentation():
    c = Canvas(str(OUT / "GlycoAhead-Presentation.pdf"), pagesize=(W,H))
    c.setTitle("GlycoAhead - Project Presentation"); c.setAuthor(META["member_name"])
    base(c, "GlycoAhead", 1)
    text(c, "Anticipating a new high-glucose episode<br/>from history, CGM and recorded context", 44, 135, 830, 31, INK, True)
    text(c, "A focused digital-twin proof of concept with a working replay application and patient-separated model evaluation.", 44, 244, 800, 21, MUTED, limit=80)
    box(c, 40, 358, 880, 100, escape(META["member_name"]) + " | Solo participant",
        escape(META["college"]) + "<br/>Python / ML / database / backend / frontend / evaluation", 16, MINT)
    c.showPage()
    columns(c, "The problem and intended healthcare workflow", 2, "Problem",
            ["A present glucose value does not show whether a new episode will begin soon.",
             "Recent glucose patterns and recorded context may support earlier review.",
             "Warnings must be assessed against false-alert burden and actual lead time."],
            "Intended use",
            ["Clinician or researcher reviewing adult Type 2 diabetes CGM records.",
             "Inspect an alert with its glucose trend, history, meals and medication context.",
             "Support review; no automated dosing, diagnosis or treatment recommendation."])
    columns(c, "A precise event, rather than an undefined 'spike'", 3, "Prediction contract",
            ["13 contiguous readings cover the preceding three hours.",
             "Predict a new onset at +15, +30, +45 or +60 minutes.",
             "Output is event probability, not an exact future glucose value."],
            "Endpoint and confirmation",
            ["Two readings >180 mg/dL, preceded by two readings <=180 mg/dL.",
             "Onset is the first high reading; the latest two inputs must be <=180.",
             "Full outcome confirmation requires readings through +75 minutes."],
            "Illustration: an alert at 12:00 and an onset at 12:30 provide 30 minutes of warning, not 60.")
    columns(c, "Dataset: linked observations from the same people", 4, "ShanghaiT2DM v5",
            ["100 unique patients; 109 recordings.",
             "112,462 retained numeric CGM readings at native 15-minute cadence.",
             "Linked clinical summary and timestamped meal/medication entries.",
             "Variable recording lengths; no invented padding."],
            "Provenance and boundaries",
            ["Recording identifiers link history and sensor data.",
             "Source hashes, quality checks and original timestamps are retained.",
             "No unrelated EHR-to-wearable joins.",
             "Chinese cohort; no Indian external validation."],
            "Sources: Figshare dataset 21600933, version 5; Scientific Data, doi:10.1038/s41597-023-01940-7.")
    columns(c, "Two data streams, 54 deployed predictive inputs", 5, "History and glucose",
            ["Age and diabetes duration; assumed available at enrollment.",
             "13 glucose lags; mean, variability, minimum and maximum.",
             "15- and 60-minute slopes, prior high fraction and time of day.",
             "Undated labs and outcome summaries excluded."],
            "Recorded context",
            ["Meal counts, timing, food categories and documented portions.",
             "Medication entries, timing and some documented doses.",
             "Estimated carbs, protein, fat, fibre and energy.",
             "Nutrition coverage and assumption indicators."])
    columns(c, "Food references are estimates, not measured intake", 6, "Nutrition pipeline",
            ["Match a recorded food to a preparation-specific reference.",
             "Scale per-100-g nutrients to the documented edible amount.",
             "Use explicit generic recipe assumptions for supported mixed dishes.",
             "Freeze catalog contents with the model version."],
            "Missingness and medication",
            ["Unknown food or quantity remains missing, not zero.",
             "Incomplete meal totals are not silently presented as complete.",
             "Medication features describe documented context.",
             "No insulin-on-board estimate or causal dosing simulation."])
    architecture(c, 7)
    columns(c, "Training and tuning without patient overlap", 8, "One outer assignment",
            ["60 patients fit the model; 10 calibrate probabilities.",
             "10 select alert thresholds; 20 evaluate performance.",
             "All visits from one patient remain in the same group.",
             "Three predefined patient assignments examine robustness."],
            "Training-only selection",
            ["Histogram gradient boosting with sigmoid calibration.",
             "Eight fixed settings; three inner folds within the 60 training patients.",
             "Rank by inner patient-weighted average precision.",
             "Refit, calibrate, select threshold and evaluate separately."])
    columns(c, "Digital twin: an evolving predictive state", 9, "Implemented lifecycle",
            ["New patient starts with population predictions.",
             "Only matured outcomes update a bounded patient risk offset.",
             "Cold start: at least 20 spaced outcomes and 24 hours.",
             "State resets at gaps and recording boundaries."],
            "What is established",
            ["The state-update and provenance mechanisms are implemented.",
             "Base model weights stay frozen during replay.",
             "Personalized candidate is visible alongside population risk.",
             "Personalization benefit is not established; population alerts remain active."])
    columns(c, "Working product: five connected views", 10, "Inspect the patient",
            ["Patient workspace: replay, glucose and probability timelines.",
             "Meals, medicines, patient state and alert acknowledgement.",
             "Inspect prediction: saved features, model and state.",
             "Outage simulation: withhold forecasts until history recovers."],
            "Inspect the system",
            ["Patient cohort: linked recordings, lengths and split membership.",
             "Model evidence: selected model and repeated comparisons.",
             "Food reference: nutrients, mappings and source metadata.",
             "How it works: workflow plus documented API."],
            "Recorded replay is clearly distinguished from a connected live wearable.")
    result_slide(c)
    columns(c, "Engineering and reproducibility", 12, "Implemented",
            ["FastAPI + React/TypeScript; one local worker.",
             "SQLite, SQLAlchemy and Alembic migrations.",
             "Versioned model/catalog, checksums and prediction snapshots.",
             "Health endpoint, request logs and stale-request handling."],
            "Repository evidence",
            ["Pinned dependencies and local setup/start scripts.",
             "Existing split/meal-chronology tests and CI build definition.",
             "Architecture, model card and aggregate comparison reports.",
             "Docker files included; Docker deployment not yet validated."])
    columns(c, "Limits that define the next evaluation", 13, "Data and model",
            ["Short recordings and only 100 participants.",
             "Uncertain availability timing for some clinical/context fields.",
             "Estimated nutrition and potentially missing meal entries.",
             "The deployed model exceeds the proposed <=1 false alert/day target."],
            "Evidence still required",
            ["External validation, including Indian population data.",
             "Clinician review and prospective usefulness assessment.",
             "Demonstrated benefit from patient personalization.",
             "No clinical safety, production scale or compliance claims."])
    columns(c, "Future scope and delivery", 14, "Next technical steps",
            ["Broader, longer-duration patient data.",
             "Live CGM adapter with duplicates, late data and gap handling.",
             "Richer reliably timestamped activity, sleep and treatment context.",
             "Controlled evaluation before enabling personalized alerts."],
            "Submission deliverables",
            ["Working application and source repository package.",
             "Architecture PDF and this presentation.",
             "Selected calibrated model and aggregate evidence.",
             "Video recorded; unlisted YouTube link being added to README."],
            "Goal: a useful, inspectable forecasting workflow that can be evaluated and extended.")
    base(c, "References, licensing and project identity", 15)
    text(c, "<b>Surajkumar Reddiar</b> | Solo participant<br/>Rajiv Gandhi Institute of Technology", 44, 129, 870, 21)
    refs = [
        ("Dataset: Shanghai diabetes dataset, v5", "https://doi.org/10.6084/m9.figshare.21600933.v5"),
        ("Original data descriptor: Scientific Data (2023)", "https://doi.org/10.1038/s41597-023-01940-7"),
        ("Project evidence: source code and frozen aggregate reports", "README.md; docs/MODEL_CARD.md; docs/TUNING.md; release/selected_model/comparison.json"),
    ]
    for i, (label, url) in enumerate(refs):
        y=213+i*65
        text(c,label,44,y,870,16,GREEN,True)
        text(c,escape(url),44,y+25,870,12,MUTED)
        if url.startswith("https://"):
            c.linkURL(url,(44,H-y-45,900,H-y-21),relative=0)
    text(c,"Code: MIT. Shanghai data: CC BY 4.0. Nutrition references and dependencies retain their separate terms; code licensing does not relicense third-party data.",44,424,870,15,limit=60)
    c.showPage(); c.save()


def main():
    OUT.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    c=Canvas(str(OUT/"GlycoAhead-Architecture.pdf"), pagesize=(W,H))
    c.setTitle("GlycoAhead - Architecture"); c.setAuthor(META["member_name"])
    architecture(c); state_architecture(c); c.save()
    presentation()
    for name in ("GlycoAhead-Architecture.pdf","GlycoAhead-Presentation.pdf"):
        shutil.copy2(OUT/name,DOCS/name)
        print(DOCS/name)


if __name__ == "__main__":
    main()
