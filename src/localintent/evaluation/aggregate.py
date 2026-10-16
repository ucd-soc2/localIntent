"""Recompute cohort summaries from individual saved evaluations."""

from __future__ import annotations

import statistics
from pathlib import Path

from ..artifacts import METRICS, METHODS, MODELS, write_csv, write_json
from .metrics import score_output

GROUPS = ("all", "non_persistent", "rule", "command", "clarification", "rejection")


def in_group(row, group):
    return (
        group == "all"
        or row["outcome"] == group
        or (group == "non_persistent" and row["outcome"] != "rule")
    )


def percentile(values, quantile=0.95):
    """Linear interpolation between adjacent observations, as in NumPy."""
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (position - lower) * (values[upper] - values[lower])


def summaries(rows):
    result = []
    for model in (*MODELS, "all"):
        for group in GROUPS:
            for method in METHODS:
                selected = [
                    r
                    for r in rows
                    if (model == "all" or r["model"] == model)
                    and r["method"] == method
                    and in_group(r, group)
                ]
                if not selected:
                    continue
                scores = [r["metrics"] for r in selected if r["metrics"] is not None]
                item = {
                    "model": model,
                    "method": method,
                    "group": group,
                    "n": len(selected),
                    "scored_n": len(scores),
                    "missing_n": len(selected) - len(scores),
                }
                for metric in METRICS:
                    count = sum(s[metric] for s in scores)
                    item[f"{metric}_count"] = count
                    item[f"{metric}_rate"] = count / len(scores) if scores else None
                item["checker_passed"] = sum(
                    bool(r["final"]["checker_passed"]) for r in selected
                )
                result.append(item)
    return result


def paired_summaries(rows):
    result = []
    for model in (*MODELS, "all"):
        for group in GROUPS:
            selected = [
                r
                for r in rows
                if r["method"] == "semantic_repair"
                and (model == "all" or r["model"] == model)
                and in_group(r, group)
            ]
            if not selected:
                continue
            pairs = [
                (score_output(r["initial"]["output"], r), r["metrics"])
                for r in selected
            ]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            item = {
                "model": model,
                "group": group,
                "n": len(selected),
                "paired_n": len(pairs),
                "triggered": sum(bool(r["repair"]["triggered"]) for r in selected),
                "accepted": sum(bool(r["repair"]["accepted"]) for r in selected),
                "repair_model_calls": sum(r["repair"]["model_calls"] for r in selected),
            }
            for metric in METRICS:
                item[f"{metric}_initial"] = sum(a[metric] for a, _ in pairs)
                item[f"{metric}_final"] = sum(b[metric] for _, b in pairs)
                item[f"{metric}_gains"] = sum(b[metric] > a[metric] for a, b in pairs)
                item[f"{metric}_losses"] = sum(b[metric] < a[metric] for a, b in pairs)
            result.append(item)
    return result


def latency_summaries(rows):
    result = []
    for model in MODELS:
        for group in ("non_persistent", "rule"):
            for method in METHODS:
                values = [
                    r["timing_seconds"]["end_to_end"]
                    for r in rows
                    if r["model"] == model
                    and r["method"] == method
                    and in_group(r, group)
                ]
                if values:
                    result.append(
                        {
                            "model": model,
                            "method": method,
                            "group": group,
                            "n": len(values),
                            "mean": statistics.mean(values),
                            "median": statistics.median(values),
                            "p95": percentile(values),
                        }
                    )
    return result


def stage_summaries(rows):
    result = []
    for model in MODELS:
        for group in ("non_persistent", "rule"):
            selected = [r for r in rows if r["model"] == model and in_group(r, group)]
            for label in (
                "two_stage_routing",
                "two_stage_generation",
                "repair_initial",
                "repair_model",
            ):
                method = (
                    "two_stage" if label.startswith("two_stage") else "semantic_repair"
                )
                arm = [r for r in selected if r["method"] == method]
                values = []
                for row in arm:
                    calls = row["model_calls"]
                    if label == "two_stage_routing":
                        values.append(
                            sum(
                                c["elapsed_time_sec"]
                                for c in calls
                                if c["stage"] == "stage1"
                            )
                        )
                    elif label == "two_stage_generation":
                        values.append(
                            sum(
                                c["elapsed_time_sec"]
                                for c in calls
                                if c["stage"] == "stage2"
                            )
                        )
                    elif label == "repair_initial":
                        values.append(
                            sum(
                                c["elapsed_time_sec"]
                                for c in calls
                                if c["stage"]
                                in ("routing", "initial_generation", "generation")
                            )
                        )
                    elif row["experiment"] == "paper":
                        repair_calls = [
                            c["elapsed_time_sec"]
                            for c in calls
                            if c["stage"] == "semantic_repair"
                        ]
                        if repair_calls:
                            values.append(sum(repair_calls))
                    elif row["repair"]["model_calls"]:
                        values.append(sum(c["elapsed"] for c in row["transport"]))
                result.append(
                    {
                        "model": model,
                        "group": group,
                        "stage": label,
                        "cohort_n": len(arm),
                        "called_n": len(values),
                        "mean": statistics.mean(values) if values else None,
                    }
                )
    return result


def export(rows, destination: Path):
    tables = {
        "metrics": summaries(rows),
        "repair_pairs": paired_summaries(rows),
        "latency": latency_summaries(rows),
        "stage_latency": stage_summaries(rows),
    }
    for name, table in tables.items():
        write_csv(destination / f"{name}.csv", table)
    missing = [
        {"model": r["model"], "method": r["method"], "id": r["id"]}
        for r in rows
        if r["metrics"] is None
    ]
    write_json(
        destination / "summary.json",
        {
            "evaluations": len(rows),
            "scored": len(rows) - len(missing),
            "missing_scores": missing,
            "overall_repair": next(
                x
                for x in tables["repair_pairs"]
                if x["model"] == "all" and x["group"] == "all"
            ),
        },
    )
    return tables
