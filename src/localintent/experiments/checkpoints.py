"""Atomic, checksummed checkpoints bound to inputs and run configuration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ..artifacts import canonical


class IntegrityError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def seal(path, value, identity):
    payload = {"identity": identity, "data": value}
    write(path, {**payload, "sha256": digest(payload)})


def load(path, identity=None):
    try:
        envelope = json.loads(Path(path).read_text(encoding="utf-8"))
        if envelope["sha256"] != digest(
            {"identity": envelope["identity"], "data": envelope["data"]}
        ):
            raise IntegrityError(f"Checkpoint checksum mismatch: {path}")
        if identity is not None and envelope["identity"] != identity:
            raise IntegrityError(f"Checkpoint identity mismatch: {path}")
        return envelope["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise IntegrityError(f"Invalid checkpoint: {path}") from error
