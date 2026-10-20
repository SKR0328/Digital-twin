import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="GlycoAhead local research workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    importer = commands.add_parser("import-shanghai")
    importer.add_argument("folder", type=Path)
    importer.add_argument("--summary", type=Path, help="Use an explicitly selected original clinical-summary workbook")
    trainer = commands.add_parser("train")
    trainer.add_argument("--horizon", type=int, choices=[30, 60], default=60)
    trainer.add_argument("--context", action="store_true", help="Include timestamped meal/medication entries")
    trainer.add_argument("--nutrition", action="store_true", help="Include versioned cooked/as-served nutrient estimates and context")
    trainer.add_argument("--development-only", action="store_true", help="Withhold test metrics and keep current active model")
    trainer.add_argument("--no-activate", action="store_true")
    experiments = commands.add_parser("compare-features", help="Run predefined patient splits and feature comparisons without activation")
    experiments.add_argument("--seeds", nargs="+", type=int, default=[2026, 2027, 2028])
    experiments.add_argument("--reference-version", help="Freeze configuration and catalog from this registered model; default active version")
    baseline = commands.add_parser("compare-baseline", help="Add a glucose/trend baseline to an existing completed comparison")
    baseline.add_argument("--experiment", required=True, help="Existing local experiment identifier")
    tuner = commands.add_parser("tune-settings", help="Patient-separated inner-CV search on an existing comparison")
    tuner.add_argument("--experiment", required=True)
    variant_tuner = commands.add_parser("tune-meal-variants", help="Tune meal timing and pre-meal glucose on training patients only")
    variant_tuner.add_argument("--experiment", required=True)
    promoter = commands.add_parser("promote-tuned", help="Activate the reviewed seed-2026 training-only tuning winner")
    promoter.add_argument("--experiment", required=True)
    installer = commands.add_parser("install-model", help="Install a trusted packaged model; never use untrusted joblib files")
    installer.add_argument("folder", type=Path)
    nutrition_importer = commands.add_parser("import-nutrition")
    nutrition_importer.add_argument("catalog", type=Path)
    activator = commands.add_parser("activate")
    activator.add_argument("version")
    activator.add_argument("--development-demo", action="store_true", help="Explicitly activate a validation-only candidate for local research replay")
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "init":
        from .db import initialize
        initialize()
        print("Database migrated.")
    elif args.command == "import-shanghai":
        from .db import initialize
        from .ingestion import import_shanghai
        initialize()
        print(json.dumps(import_shanghai(args.folder, args.summary), indent=2))
    elif args.command == "train":
        from .training import train
        train(args.horizon, activate=not (args.no_activate or args.development_only), context=args.context, development_only=args.development_only, nutrition=args.nutrition)
    elif args.command == "compare-features":
        from .experiments import run_experiments
        run_experiments(args.seeds, args.reference_version)
    elif args.command == "compare-baseline":
        from .baseline_experiment import compare_baseline
        compare_baseline(args.experiment)
    elif args.command == "tune-settings":
        from .tuning import tune_settings
        tune_settings(args.experiment)
    elif args.command == "promote-tuned":
        from .deployment import promote_tuned
        print(json.dumps(promote_tuned(args.experiment), indent=2))
    elif args.command == "tune-meal-variants":
        from .variant_tuning import tune_meal_variants
        tune_meal_variants(args.experiment)
    elif args.command == "install-model":
        from .deployment import install_release
        print(json.dumps(install_release(args.folder), indent=2))
    elif args.command == "import-nutrition":
        from .db import initialize
        from .nutrition import import_catalog
        initialize()
        print(json.dumps(import_catalog(args.catalog), indent=2))
    elif args.command == "activate":
        from .ml import activate_version
        activate_version(args.version, development_demo=args.development_demo)
        print("Model activated for new replays. Existing sessions remain pinned.")
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("glycoahead.api:app", host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
