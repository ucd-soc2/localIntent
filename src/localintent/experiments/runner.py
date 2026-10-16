"""Serial experiment execution with separate paper and extended designs."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import platform
import time
from pathlib import Path

from .. import core, methods
from ..artifacts import METHODS, dataset, sha256, write_json
from ..evaluation.aggregate import export
from ..evaluation.metrics import score_output
from ..inference import Transport, api, inspect_models, prepare_model
from ..repair import grounded, validation_guided
from .checkpoints import IntegrityError, digest, load, seal, write


def make_plan(
    root, experiment, cohort, models=None, limit=None, api_base="http://127.0.0.1:11439"
):
    config = json.loads((root / f"configs/{experiment}.json").read_text())
    if experiment == "paper" and cohort != "original":
        raise ValueError("The paper design uses only the original cohort")
    data = dataset(root, cohort)
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        data = data[:limit]
    if models:
        if len(models) != len(set(models)) or any(
            m not in config["models"] for m in models
        ):
            raise ValueError("Select distinct models from the recorded experiment")
        config["models"] = models
    sources = {
        str(p.relative_to(root)): sha256(p)
        for p in sorted((root / "src/localintent").rglob("*"))
        if p.is_file() and p.suffix in (".py", ".txt")
    }
    return {
        "experiment": experiment,
        "cohort": cohort,
        "config": config,
        "sample_ids": [r["id"] for r in data],
        "data_sha256": digest(data),
        "sources": sources,
        "evaluations": len(data) * len(config["models"]) * 4,
        "api_base": api_base,
        "limited_run": limit is not None or bool(models),
    }, data


def execute_one(record, method, model, config, transport, initial_row=None):
    original_call = core.call_ollama
    core.call_ollama = transport
    start = time.perf_counter()
    settings = config["settings"]
    url = transport.base.rstrip("/") + "/api/generate"
    initial = candidate = repair = local = raw = None
    calls = []
    initial_raw = candidate_raw = None
    try:
        if method != "semantic_repair":
            final, local, raw = methods.execute(
                {"input": copy.deepcopy(record["input"])},
                method,
                model,
                url,
                settings["timeout"],
            )
            calls = local["ollama_calls"]
        elif config["shared_initial"]:
            if initial_row is None:
                raise IntegrityError(
                    "Grounded repair requires a completed shared initial"
                )
            initial = copy.deepcopy(initial_row["final"])
            local = copy.deepcopy(initial_row["details"]["local"])
            state = record["input"]
            repair = grounded.repair_initial(
                state["userInstruction"],
                state["current_state"],
                state["timestamp"],
                initial,
                candidate_generator=lambda prompt: transport(
                    model, prompt, url, settings["timeout"]
                )[0],
                route_mode=local["route_mode"],
            )
            final, candidate = repair["final"], repair["candidate"]
            calls = local["ollama_calls"]
            initial_raw = initial_row.get("raw_output")
            candidate_raw = (
                transport.observed[-1]["raw"] if transport.observed else None
            )
        else:
            result = validation_guided.execute(
                {"input": copy.deepcopy(record["input"])},
                model,
                url,
                settings["timeout"],
            )
            initial, candidate, final = (
                result["initial"],
                result["candidate"],
                result["final"],
            )
            initial_raw, candidate_raw, raw = (
                result["initial_raw_output"],
                result["candidate_raw_output"],
                result["final_raw_output"],
            )
            repair = {
                "triggered": result["repair_triggered"],
                "accepted": result["repair_accepted"],
                "reason": result["acceptance_reason"],
                "diagnostics": result["structural_diagnostics"]
                + result["semantic_diagnostics"],
                "prompt_sha256": (
                    __import__("hashlib")
                    .sha256(result["repair_prompt"].encode())
                    .hexdigest()
                    if result["repair_prompt"]
                    else None
                ),
                "model_calls": sum(
                    c["stage"] == "semantic_repair" for c in result["ollama_calls"]
                ),
            }
            calls = result["ollama_calls"]
            local = {
                "route_mode": result["route_mode"],
                "gate_raw_response": result["gate_raw_response"],
            }
        elapsed = (
            time.perf_counter()
            - start
            + sum(c["elapsed"] for c in transport.observed if c["reused_within_run"])
        )
        timing = {"end_to_end": elapsed}
        if method == "semantic_repair" and config["shared_initial"]:
            timing = {
                "initial": initial_row["timing_seconds"]["end_to_end"],
                "repair": elapsed,
                "end_to_end": initial_row["timing_seconds"]["end_to_end"] + elapsed,
            }
        return {
            "experiment": config["experiment"],
            "cohort": record["id"].split("-")[0],
            "id": record["id"],
            "model": model,
            "method": method,
            "outcome": record["outcome"],
            "input": record["input"],
            "reference": record["reference"],
            "initial": initial,
            "candidate": candidate,
            "final": final,
            "metrics": score_output(final["output"], record),
            "initial_metrics": (
                score_output(initial["output"], record) if initial else None
            ),
            "candidate_metrics": (
                score_output(candidate["output"], record) if candidate else None
            ),
            "raw_output": raw,
            "initial_raw_output": initial_raw,
            "candidate_raw_output": candidate_raw,
            "repair": repair,
            "model_calls": calls,
            "transport": transport.observed,
            "timing_seconds": timing,
            "generation_settings": settings,
            "shared_initial": method == "semantic_repair" and config["shared_initial"],
            "details": {"local": local, "route_mode": local["route_mode"]},
        }
    finally:
        core.call_ollama = original_call


def run(root, destination, plan, data, max_new=None):
    root, destination = root.resolve(), destination.resolve()
    for protected in (
        root / "results",
        root / "data",
        root / "src",
        root / "configs",
        root / "paper",
        root / "provenance",
    ):
        if destination == protected or protected in destination.parents:
            raise ValueError(
                "Choose a run directory outside published artifacts, for example runs/experiment"
            )
    destination.mkdir(parents=True, exist_ok=True)
    lock = (destination / ".lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_path = destination / "manifest.json"
        if manifest_path.exists():
            manifest = load(manifest_path)
            if manifest["plan"] != plan:
                raise IntegrityError(
                    "Run inputs, sources or configuration changed; use a new output directory"
                )
        else:
            pinned = (
                json.loads((root / "configs/models.json").read_text())
                if plan["experiment"] == "extended"
                else None
            )
            observed = inspect_models(plan["api_base"], plan["config"], pinned)
            manifest = {
                "plan": plan,
                "models": observed,
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                },
                "created_unix": time.time(),
            }
            seal(manifest_path, manifest, {"kind": "experiment_manifest"})
        plan_hash = digest(manifest)
        all_rows = {}

        def identity(model, record, method):
            return {
                "manifest_sha256": plan_hash,
                "model": model,
                "id": record["id"],
                "method": method,
                "input_sha256": digest(record["input"]),
            }

        def location(model, record, method):
            return (
                destination
                / "checkpoints"
                / model.replace(":", "_")
                / record["id"]
                / method
            )

        for model in plan["config"]["models"]:
            for record in data:
                for method in METHODS:
                    path = location(model, record, method) / "result.json"
                    if path.exists():
                        row = load(path, identity(model, record, method))
                        if (
                            row["input"] != record["input"]
                            or row["reference"] != record["reference"]
                            or score_output(row["final"]["output"], record)
                            != row["metrics"]
                        ):
                            raise IntegrityError(
                                "Saved result disagrees with input or scorer"
                            )
                        all_rows[(model, record["id"], method)] = row
        completed_before = len(all_rows)

        def schedule():
            for model in plan["config"]["models"]:
                if plan["experiment"] == "paper":
                    for outcome in ("non_persistent", "rule"):
                        for method in METHODS:
                            for record in data:
                                if (record["outcome"] == "rule") == (outcome == "rule"):
                                    yield model, record, method
                else:
                    for record in data:
                        for method in METHODS:
                            yield model, record, method

        current_model = None
        try:
            for model, record, method in schedule():
                key = (model, record["id"], method)
                if key in all_rows:
                    continue
                if max_new is not None and len(all_rows) - completed_before >= max_new:
                    break
                if current_model != model:
                    inspect_models(plan["api_base"], plan["config"], manifest["models"])
                    prepare_model(plan["api_base"], model, plan["config"])
                    current_model = model
                transport = Transport(
                    location(model, record, method),
                    identity(model, record, method),
                    plan["api_base"],
                    plan["config"]["settings"],
                )
                row = execute_one(
                    record,
                    method,
                    model,
                    plan["config"],
                    transport,
                    all_rows.get((model, record["id"], "localintent")),
                )
                row["model_digest"] = manifest["models"][model]["digest"]
                seal(
                    location(model, record, method) / "result.json",
                    row,
                    identity(model, record, method),
                )
                all_rows[key] = row
                write(
                    destination / "status.json",
                    {
                        "completed": len(all_rows),
                        "expected": plan["evaluations"],
                        "status": "running",
                    },
                )
                print(
                    f"{len(all_rows)}/{plan['evaluations']} {model} {record['id']} {method}",
                    flush=True,
                )
                time.sleep(plan["config"]["settings"].get("request_gap_seconds", 0))
        finally:
            rows = list(all_rows.values())
            temporary = destination / "records.jsonl.tmp"
            with temporary.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(temporary, destination / "records.jsonl")
            write(
                destination / "status.json",
                {
                    "completed": len(rows),
                    "expected": plan["evaluations"],
                    "status": (
                        "complete" if len(rows) == plan["evaluations"] else "incomplete"
                    ),
                },
            )
            if len(rows) == plan["evaluations"]:
                export(rows, destination / "analysis")
        return {
            "completed": len(all_rows),
            "expected": plan["evaluations"],
            "output": str(destination),
        }
    finally:
        lock.close()
