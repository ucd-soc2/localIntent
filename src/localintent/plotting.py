"""Publication figures generated solely from saved evaluation records."""

from __future__ import annotations

from pathlib import Path
from .artifacts import METRICS, METHODS, MODELS, LABELS
from .evaluation.aggregate import export


def render(rows, destination: Path, title: str):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    import numpy as np

    destination.mkdir(parents=True, exist_ok=True)
    tables = export(rows, destination / "data")
    colors = ("#595959", "#6C8FBE", "#609887", "#C75B49")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )
    metrics = {(r["model"], r["group"], r["method"]): r for r in tables["metrics"]}
    pairs = {(r["model"], r["group"]): r for r in tables["repair_pairs"]}
    latency = {(r["model"], r["group"], r["method"]): r for r in tables["latency"]}
    stages = {(r["model"], r["group"], r["stage"]): r for r in tables["stage_latency"]}
    files = []

    def save(fig, name, heading, legend=None):
        fig.suptitle(f"{heading}\n{title}", fontsize=15, fontweight="bold", y=0.99)
        if legend:
            handles = [Patch(facecolor=c, label=l) for c, l in legend]
            fig.legend(
                handles=handles,
                loc="upper center",
                bbox_to_anchor=(0.52, 0.89),
                ncol=len(legend),
                frameon=False,
            )
        fig.subplots_adjust(
            left=0.065, right=0.99, top=0.77, bottom=0.13, hspace=0.40, wspace=0.20
        )
        for extension in ("png", "pdf", "svg"):
            fig.savefig(
                destination / f"{name}.{extension}",
                dpi=180,
                bbox_inches="tight",
                facecolor="white",
            )
        plt.close(fig)
        files.append(name)

    legend = list(zip(colors, [LABELS[m] for m in METHODS]))
    fig, axes = plt.subplots(2, 4, figsize=(14, 6))
    x = np.arange(len(METRICS))
    for i, group in enumerate(("non_persistent", "rule")):
        for j, model in enumerate(MODELS):
            ax = axes[i, j]
            for k, method in enumerate(METHODS):
                ax.bar(
                    x + (k - 1.5) * 0.19,
                    [metrics[(model, group, method)][f"{m}_rate"] for m in METRICS],
                    width=0.19,
                    color=colors[k],
                )
            ax.set(xticks=x, xticklabels=METRICS, ylim=(0, 1.05), title=model)
            ax.grid(axis="y", linestyle="--", alpha=0.2)
            ax.set_axisbelow(True)
            if j == 0:
                ax.set_ylabel("Non-persistent" if i == 0 else "Rule")
    save(fig, "method_comparison", "Six diagnostic metrics", legend)

    fig, axes = plt.subplots(2, 4, figsize=(14, 6))
    for i, group in enumerate(("non_persistent", "rule")):
        for j, model in enumerate(MODELS):
            row = pairs[(model, group)]
            ax = axes[i, j]
            for k, phase in enumerate(("initial", "final")):
                values = [row[f"{m}_{phase}"] / row["paired_n"] for m in METRICS]
                ax.bar(
                    x + (k - 0.5) * 0.34,
                    values,
                    width=0.34,
                    color=("#6E8EBC", "#C75C4A")[k],
                )
            ax.set(xticks=x, xticklabels=METRICS, ylim=(0, 1.05), title=model)
            ax.grid(axis="y", alpha=0.2)
            if j == 0:
                ax.set_ylabel("Non-persistent" if i == 0 else "Rule")
    save(
        fig,
        "repair_initial_final",
        "Paired repair metrics",
        [("#6E8EBC", "Initial"), ("#C75C4A", "Final")],
    )

    for statistic, label in (
        ("p95", "95th percentile"),
        ("mean", "Mean"),
        ("median", "Median"),
    ):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for ax, group in zip(axes, ("non_persistent", "rule")):
            for k, method in enumerate(METHODS):
                ax.bar(
                    np.arange(4) + (k - 1.5) * 0.19,
                    [latency[(m, group, method)][statistic] for m in MODELS],
                    width=0.19,
                    color=colors[k],
                )
            ax.set(
                xticks=np.arange(4),
                xticklabels=MODELS,
                ylabel="Seconds",
                title="Non-persistent" if group == "non_persistent" else "Rule",
            )
            ax.grid(axis="y", alpha=0.2)
        save(fig, f"latency_{statistic}", f"{label} end-to-end latency", legend)

    fig, axes = plt.subplots(1, 4, figsize=(14, 4.5))
    for ax, model in zip(axes, MODELS):
        for k, method in enumerate(METHODS):
            ax.bar(
                x + (k - 1.5) * 0.19,
                [metrics[(model, "all", method)][f"{m}_rate"] for m in METRICS],
                width=0.19,
                color=colors[k],
            )
        ax.set(xticks=x, xticklabels=METRICS, ylim=(0, 1.05), title=model)
        ax.grid(axis="y", alpha=0.2)
    save(fig, "overall_comparison", "Overall diagnostic metrics", legend)

    stage_names = (
        "two_stage_routing",
        "two_stage_generation",
        "repair_initial",
        "repair_model",
    )
    stage_labels = (
        "TSG routing",
        "TSG generation",
        "Repair initial",
        "Repair LLM call",
    )
    stage_colors = ("#7EA5C8", "#4B779D", "#7FAD94", "#D8856A")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, group in zip(axes, ("non_persistent", "rule")):
        for k, stage in enumerate(stage_names):
            for j, model in enumerate(MODELS):
                entry = stages[(model, group, stage)]
                position = j + (k - 1.5) * 0.19
                if entry["mean"] is None:
                    ax.annotate(
                        "No call",
                        (position, 0),
                        rotation=90,
                        fontsize=7,
                        ha="center",
                        va="bottom",
                    )
                else:
                    ax.bar(position, entry["mean"], width=0.19, color=stage_colors[k])
                    if stage == "repair_model":
                        ax.annotate(
                            f"{entry['called_n']}/{entry['cohort_n']}",
                            (position, entry["mean"]),
                            xytext=(0, 3),
                            textcoords="offset points",
                            ha="center",
                            fontsize=8,
                        )
        ax.set(
            xticks=np.arange(4),
            xticklabels=MODELS,
            ylabel="Recorded model-call seconds",
            title="Non-persistent" if group == "non_persistent" else "Rule",
        )
        ax.margins(y=0.22)
        ax.grid(axis="y", alpha=0.2)
    save(
        fig,
        "stage_latency",
        "Model-call latency by stage",
        list(zip(stage_colors, stage_labels)),
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax, group in zip(axes, ("non_persistent", "rule")):
        for k, field in enumerate(("triggered", "accepted")):
            values = [pairs[(m, group)][field] / pairs[(m, group)]["n"] for m in MODELS]
            ax.bar(
                np.arange(4) + (k - 0.5) * 0.35,
                values,
                width=0.35,
                color=("#6C8FBE", "#C75B49")[k],
            )
        ax.set(
            xticks=np.arange(4),
            xticklabels=MODELS,
            ylim=(0, 1.05),
            ylabel="Fraction of scenarios",
            title="Non-persistent" if group == "non_persistent" else "Rule",
        )
    save(
        fig,
        "repair_rates",
        "Repair trigger and acceptance rates",
        [("#6C8FBE", "Triggered"), ("#C75B49", "Accepted")],
    )
    return files
