"""Download and verify the hash-addressed model snapshots used by extended experiments."""

from pathlib import Path
import hashlib
import json
import os
import urllib.request

BASE = None
MODEL_DIRECTORY = None


def configure(root, directory=None):
    global BASE, MODEL_DIRECTORY
    BASE = Path(root)
    MODEL_DIRECTORY = Path(directory) if directory else BASE / ".models"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metadata():
    return json.loads((BASE / "configs/models.json").read_text())


def assets():
    found = {}
    for tag, entry in metadata().items():
        manifest_bytes = entry["manifest_text"].encode()
        if hashlib.sha256(manifest_bytes).hexdigest() != entry["digest"]:
            raise RuntimeError("Frozen model manifest hash differs: " + tag)
        manifest = json.loads(entry["manifest_text"])
        name = tag.split(":")[0]
        for layer in [manifest["config"]] + manifest["layers"]:
            digest = layer["digest"]
            found.setdefault(digest, {"size": layer["size"], "repository": name})
    return found


def install_manifests():
    for tag, entry in metadata().items():
        name, version = tag.split(":")
        path = MODEL_DIRECTORY / "manifests/registry.ollama.ai/library" / name / version
        content = entry["manifest_text"].encode()
        if hashlib.sha256(content).hexdigest() != entry["digest"]:
            raise RuntimeError("Frozen manifest checksum mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != content:
            raise RuntimeError(
                "Different model manifest already present; do not mix model versions: "
                + tag
            )
        if not path.exists():
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, path)


def download_models():
    install_manifests()
    all_assets = assets()
    for digest, info in all_assets.items():
        path = MODEL_DIRECTORY / "blobs" / digest.replace(":", "-")
        expected = digest.split(":", 1)[1]
        if path.exists():
            if path.stat().st_size != info["size"] or sha(path) != expected:
                raise RuntimeError(
                    "Existing blob failed checksum; preserved for inspection: "
                    + str(path)
                )
            print("Already verified:", digest, flush=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        start = part.stat().st_size if part.exists() else 0
        if start > info["size"]:
            raise RuntimeError("Oversized partial blob; preserved: " + str(part))
        if start < info["size"]:
            url = f"https://registry.ollama.ai/v2/library/{info['repository']}/blobs/{digest}"
            headers = {"User-Agent": "Ollama-Frozen-Model-Reproduction"}
            if start:
                headers["Range"] = f"bytes={start}-"
            print(f'Downloading {digest}: {start}/{info["size"]} bytes', flush=True)
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=120
            ) as response:
                if start and response.status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {start}-"):
                        raise RuntimeError(
                            "Range response does not match saved download"
                        )
                    mode = "ab"
                elif response.status == 200:
                    mode = "wb"  # Server ignored Range; restart this partial blob.
                elif not start and response.status == 206:
                    mode = "wb"
                else:
                    raise RuntimeError(
                        "Unexpected download status: " + str(response.status)
                    )
                with part.open(mode) as output:
                    for block in iter(lambda: response.read(4 * 1024 * 1024), b""):
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
        if part.stat().st_size != info["size"] or sha(part) != expected:
            raise RuntimeError(
                "Downloaded blob failed size/hash check; partial retained: " + str(part)
            )
        os.replace(part, path)
        print("Verified:", digest, flush=True)
    verify_models()


def verify_models():
    for tag, entry in metadata().items():
        name, version = tag.split(":")
        path = MODEL_DIRECTORY / "manifests/registry.ollama.ai/library" / name / version
        if not path.is_file() or sha(path) != entry["digest"]:
            raise RuntimeError(
                "Frozen model missing or changed. Run: python reproduce.py download-models"
            )
    for digest, info in assets().items():
        path = MODEL_DIRECTORY / "blobs" / digest.replace(":", "-")
        if (
            not path.is_file()
            or path.stat().st_size != info["size"]
            or sha(path) != digest.split(":", 1)[1]
        ):
            raise RuntimeError(
                "Model blob missing or changed. Run: python reproduce.py download-models"
            )
    print("MODEL_FILES_PASS: all four frozen models complete and verified")
