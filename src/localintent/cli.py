"""Command-line entry points for the LocalIntent research artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from .artifacts import dataset, read_jsonl, records, repository_root, write_json


def selections(experiment, cohort):
    if experiment in ("all", "paper"):
        if experiment == "paper" and cohort not in ("all", "original"):
            raise ValueError("The paper experiment uses the original cohort")
        yield "paper", "original"
    if experiment in ("all", "extended"):
        for value in (
            ("original", "supplemental", "pooled") if cohort == "all" else (cohort,)
        ):
            yield "extended", value


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="LocalIntent: paper and extended experiment reproduction"
    )
    parser.add_argument(
        "--root", type=Path, help="Repository containing data, configs and results"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help="Verify all saved scores, repair policies and artifact checksums offline",
    )
    verify.add_argument("--output", type=Path)
    for command in ("analyze", "plot"):
        sub = commands.add_parser(command)
        sub.add_argument(
            "--experiment", choices=("all", "paper", "extended"), default="all"
        )
        sub.add_argument(
            "--cohort",
            choices=("all", "original", "supplemental", "pooled"),
            default="all",
        )
        sub.add_argument(
            "--records", type=Path, help="Analyze a fresh run's records.jsonl instead"
        )
        sub.add_argument("--output", type=Path)
    for command in ("download-models", "verify-models", "list-models"):
        sub = commands.add_parser(command)
        sub.add_argument("--model-dir", type=Path)
    check = commands.add_parser("check-api")
    check.add_argument(
        "--experiment", choices=("paper", "extended"), default="extended"
    )
    check.add_argument("--api", default="http://127.0.0.1:11439")
    serve = commands.add_parser("serve")
    serve.add_argument("--ollama", default="ollama", help="Installed Ollama executable")
    serve.add_argument("--model-dir", type=Path)
    run_parser = commands.add_parser("run")
    run_parser.add_argument(
        "--experiment", choices=("paper", "extended"), required=True
    )
    run_parser.add_argument(
        "--cohort", choices=("original", "supplemental"), default="original"
    )
    run_parser.add_argument("--models", nargs="+")
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--max-new", type=int)
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--api", default="http://127.0.0.1:11439")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the run plan without connecting to a model",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else repository_root()
    if args.command == "verify":
        from .evaluation.verify import verify_release

        result = verify_release(root)
        write_json(args.output or root / "build/verification.json", result)
    elif args.command in ("analyze", "plot"):
        from .evaluation.aggregate import export

        destination = args.output or root / (
            "build/results" if args.command == "analyze" else "build/figures"
        )
        result = []
        jobs = (
            [("fresh", "run", read_jsonl(args.records))]
            if args.records
            else [
                (e, c, records(root, e, c))
                for e, c in selections(args.experiment, args.cohort)
            ]
        )
        for experiment, cohort, rows in jobs:
            path = destination if args.records else destination / experiment / cohort
            if args.command == "analyze":
                export(rows, path)
            else:
                from .plotting import render

                n = len({r["id"] for r in rows})
                render(rows, path, f"{experiment.title()} / {cohort} (n={n})")
            result.append(
                {
                    "experiment": experiment,
                    "cohort": cohort,
                    "records": len(rows),
                    "output": str(path),
                }
            )
    elif args.command in ("download-models", "verify-models", "list-models"):
        from . import models

        models.configure(root, args.model_dir)
        if args.command == "download-models":
            models.download_models()
        elif args.command == "verify-models":
            models.verify_models()
        else:
            print(
                json.dumps(
                    {k: v["digest"] for k, v in models.metadata().items()}, indent=2
                )
            )
        return
    elif args.command == "serve":
        import socket

        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 11439)) == 0:
                raise RuntimeError("Port 11439 is already occupied")
        environment = dict(
            os.environ,
            OLLAMA_HOST="127.0.0.1:11439",
            OLLAMA_MODELS=str((args.model_dir or root / ".models").resolve()),
            OLLAMA_NUM_PARALLEL="1",
            OLLAMA_MAX_LOADED_MODELS="1",
        )
        subprocess.run([args.ollama, "serve"], env=environment, check=True)
        return
    elif args.command == "check-api":
        from .inference import inspect_models

        config = json.loads((root / f"configs/{args.experiment}.json").read_text())
        locked = (
            json.loads((root / "configs/models.json").read_text())
            if args.experiment == "extended"
            else None
        )
        result = inspect_models(args.api, config, locked)
    else:
        from .experiments.runner import make_plan, run

        if args.max_new is not None and args.max_new < 0:
            parser.error("--max-new must be nonnegative")
        plan, data = make_plan(
            root, args.experiment, args.cohort, args.models, args.limit, args.api
        )
        if args.dry_run:
            result = {k: v for k, v in plan.items() if k != "sources"}
            result["source_files"] = len(plan["sources"])
        else:
            result = run(
                root,
                args.output or root / f"runs/{args.experiment}-{args.cohort}",
                plan,
                data,
                args.max_new,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
