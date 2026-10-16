"""Offline integrity, scoring, pairing and repair-policy verification."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..artifacts import METRICS, METHODS, MODELS, canonical, dataset, records, sha256
from .. import core
from ..repair import grounded, validation_guided
from .aggregate import paired_summaries
from .metrics import score_output


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_rows(rows, data, experiment):
    expected = {
        (m, d["id"], method) for m in MODELS for d in data for method in METHODS
    }
    actual = [(r["model"], r["id"], r["method"]) for r in rows]
    require(
        len(actual) == len(set(actual)) and set(actual) == expected,
        "Incomplete or duplicate evaluation matrix",
    )
    lookup = dict(zip(actual, rows))
    inputs = {r["id"]: r for r in data}
    repaired = 0
    for row in rows:
        key = (row["model"], row["id"], row["method"])
        original = inputs[row["id"]]
        require(
            row["input"] == original["input"]
            and row["reference"] == original["reference"],
            f"Dataset mismatch: {key}",
        )
        require(
            score_output(row["final"]["output"], row) == row["metrics"],
            f"Score mismatch: {key}",
        )
        require(
            row["metrics"] is None
            or (
                set(row["metrics"]) == set(METRICS)
                and all(v in (0, 1) for v in row["metrics"].values())
            ),
            f"Invalid metrics: {key}",
        )
        if row["method"] != "semantic_repair":
            continue
        repaired += 1
        if experiment == "extended":
            li = lookup[(row["model"], row["id"], "localintent")]
            require(
                li["final"]["output"] == row["initial"]["output"],
                f"Shared initial mismatch: {key}",
            )
            require(
                abs(
                    row["timing_seconds"]["end_to_end"]
                    - li["timing_seconds"]["end_to_end"]
                    - row["timing_seconds"]["repair"]
                )
                < 1e-8,
                f"Repair latency mismatch: {key}",
            )
            saved_calls = iter(row["transport"])
            consumed = []

            def generate(prompt):
                response = next(saved_calls)
                require(
                    hashlib.sha256(prompt.encode()).hexdigest()
                    == response["prompt_sha256"],
                    f"Repair prompt changed: {key}",
                )
                consumed.append(response)
                return response["raw"]

            state = original["input"]
            initial_check = core.validate_model_output(
                li["transport"][-1]["raw"], state["current_state"]
            )
            require(
                hashlib.sha256(canonical(initial_check).encode()).hexdigest()
                == li["validation_sha256"],
                f"Initial validation changed: {key}",
            )
            result = grounded.repair_initial(
                state["userInstruction"],
                state["current_state"],
                state["timestamp"],
                initial_check,
                candidate_generator=generate,
                route_mode=row["route_mode"],
            )
            for field in ("triggered", "accepted", "reason", "model_calls"):
                require(
                    result[field] == row["repair"][field],
                    f"Repair decision changed: {key} {field}",
                )
            require(
                result["final"]["output"] == row["final"]["output"],
                f"Repair output changed: {key}",
            )
            require(
                hashlib.sha256(canonical(result["final"]).encode()).hexdigest()
                == row["validation_sha256"],
                f"Repair validation changed: {key}",
            )
            require(
                len(consumed) == len(row["transport"]),
                f"Repair call count changed: {key}",
            )
        else:
            initial = row["initial"]
            structural = initial["checker_diagnostics"] or []
            semantic = validation_guided.semantic_diagnostics(
                initial["output"], row["input"]["userInstruction"]
            )
            triggered = bool(structural or semantic)
            require(
                triggered == row["repair"]["triggered"], f"Paper trigger changed: {key}"
            )
            if triggered:
                # Sorted-key result exports lose dictionary insertion order.
                # Recover the original model-input and normalized-output order.
                initial_output = (
                    core.canonicalize_output(initial["output"])
                    if initial["output"] is not None
                    else None
                )
                prompt = validation_guided.build_repair_prompt(
                    original,
                    initial_output,
                    structural,
                    semantic,
                    row["route_mode"],
                )
                require(
                    hashlib.sha256(prompt.encode()).hexdigest()
                    == row["repair"]["prompt_sha256"],
                    f"Paper repair prompt changed: {key}",
                )
            candidate = row["candidate"]
            accepted = bool(
                candidate
                and candidate["checker_passed"]
                and validation_guided.candidate_acceptable(
                    initial["output"], candidate["output"], structural, semantic
                )[0]
            )
            require(
                accepted == row["repair"]["accepted"],
                f"Paper acceptance changed: {key}",
            )
            require(
                (candidate if accepted else initial)["output"]
                == row["final"]["output"],
                f"Paper final selection changed: {key}",
            )
    return {
        "evaluations": len(rows),
        "scored": sum(r["metrics"] is not None for r in rows),
        "repair_policies_checked": repaired,
    }


def verify_release(root: Path):
    checksums = root / "provenance/checksums.json"
    if checksums.exists():
        for relative, expected in json.loads(checksums.read_text()).items():
            require(
                sha256(root / relative) == expected,
                f"Release checksum mismatch: {relative}",
            )
    result = {}
    for experiment, cohort in (
        ("paper", "original"),
        ("extended", "original"),
        ("extended", "supplemental"),
    ):
        rows = records(root, experiment, cohort)
        result[f"{experiment}/{cohort}"] = verify_rows(
            rows, dataset(root, cohort), experiment
        )
    pooled = records(root, "extended", "pooled")
    pair = next(
        r
        for r in paired_summaries(pooled)
        if r["model"] == "all" and r["group"] == "all"
    )
    require(
        len(pooled) == 5360
        and pair["paired_n"] == 1340
        and pair["APC_gains"] == 163
        and pair["APC_losses"] == 0,
        "Pooled reference totals changed",
    )
    paper = records(root, "paper")
    paired = next(
        r
        for r in paired_summaries(paper)
        if r["model"] == "all" and r["group"] == "all"
    )
    require(
        paired["paired_n"] == 619
        and paired["APC_gains"] == 30
        and paired["APC_losses"] == 3,
        "Paper paired totals changed",
    )
    passed = [
        r
        for r in paper
        if r["method"] == "localintent" and r["final"]["checker_passed"]
    ]
    result["paper_checker_counts"] = {
        "passed": len(passed),
        "passed_with_metric_failure": sum(
            any(v == 0 for v in r["metrics"].values()) for r in passed
        ),
        "paper_reports": {"passed": 511, "passed_with_metric_failure": 277},
    }
    result["status"] = "passed"
    return result
