"""Read canonical datasets and published evaluation records."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

METRICS = ("IU", "DI", "CH", "APC", "OFC", "LC")
METHODS = ("monolithic", "two_stage", "localintent", "semantic_repair")
LABELS = dict(
    zip(
        METHODS,
        ("Monolithic", "TwoStageGeneric", "LocalIntent", "LocalIntent+SemanticRepair"),
    )
)
MODELS = ("qwen2.5:3b", "gemma2:2b", "gemma3:4b", "gemma2:9b")


def repository_root() -> Path:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "configs/paper.json").is_file():
        return candidate
    raise FileNotFoundError("Supply --root pointing to the LocalIntent repository.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def dataset(root: Path, cohort: str) -> list[dict]:
    if cohort != "original":
        raise ValueError(f"Unknown cohort: {cohort}")
    return read_jsonl(root / "data/original.jsonl")


def records(root: Path, experiment: str, cohort: str = "original") -> list[dict]:
    if experiment != "paper" or cohort != "original":
        raise ValueError("Only the paper experiment and original cohort are available.")
    rows = read_jsonl(root / "results/paper/records.jsonl.gz")
    samples = {sample["id"]: sample for sample in dataset(root, cohort)}
    for row in rows:
        sample = samples[row["id"]]
        row.update(
            experiment=experiment, cohort=cohort,
            input=sample["input"], reference=sample["reference"],
            outcome=sample["outcome"],
            timing_seconds={"end_to_end": row["elapsed_seconds"]},
        )
    return rows


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
