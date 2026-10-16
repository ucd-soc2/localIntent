"""Ollama transport with complete-response caching and bounded retries."""

from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from .experiments.checkpoints import IntegrityError, load, seal


class TransportError(RuntimeError):
    pass


def api(base, endpoint, payload=None, timeout=30):
    request = urllib.request.Request(
        base.rstrip("/") + "/api/" + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def generate(model, prompt, base, settings):
    options = {
        k: settings[k]
        for k in ("num_ctx", "temperature", "seed", "top_p", "top_k", "num_thread")
        if settings.get(k) is not None
    }
    streaming = settings.get("stream", False)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": streaming,
        "keep_alive": settings["keep_alive"],
        "options": options,
    }
    request = urllib.request.Request(
        base.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(
        request, timeout=settings.get("inactivity_timeout", settings["timeout"])
    ) as response:
        if streaming:
            parts = []
            last = None
            for line in response:
                if time.perf_counter() - started > settings["timeout"]:
                    raise TimeoutError("Total generation deadline exceeded")
                if not line.strip():
                    continue
                packet = json.loads(line)
                if packet.get("error"):
                    raise TransportError(packet["error"])
                if not isinstance(packet.get("response", ""), str):
                    raise TransportError("Non-string response chunk")
                parts.append(packet.get("response", ""))
                if packet.get("done") is True:
                    last = packet
                    break
            if last is None:
                raise TransportError("Incomplete stream without done=true")
            raw = "".join(parts)
        else:
            last = json.load(response)
            if last.get("error") or last.get("done") is not True:
                raise TransportError(last.get("error", "Incomplete response"))
            raw = last.get("response", "")
            if not isinstance(raw, str):
                raise TransportError("Non-string response")
    elapsed = time.perf_counter() - started
    return (
        raw,
        elapsed,
        {
            "elapsed_time_sec": elapsed,
            "prompt_characters": len(prompt),
            "prompt_eval_count": last.get("prompt_eval_count"),
            "eval_count": last.get("eval_count"),
            "done_reason": last.get("done_reason"),
            "num_ctx": settings["num_ctx"],
            "load_duration_ns": last.get("load_duration"),
        },
    )


class Transport:
    def __init__(self, directory: Path, identity, base, settings, perform=generate):
        self.directory = directory
        self.identity = identity
        self.base = base
        self.settings = settings
        self.perform = perform
        self.index = 0
        self.observed = []

    def __call__(self, model, prompt, url, timeout):
        if model != self.identity["model"]:
            raise IntegrityError("Transport model differs from checkpoint identity")
        index = self.index
        self.index += 1
        identity = {
            **self.identity,
            "call_index": index,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "settings": self.settings,
        }
        path = self.directory / f"call_{index}.json"
        if path.exists():
            value = load(path, identity)
            self.observed.append({**value, "reused_within_run": True})
            return value["raw"], value["elapsed"], dict(value["metadata"])
        for attempt in range(3):
            try:
                raw, elapsed, metadata = self.perform(
                    model, prompt, self.base, self.settings
                )
                value = {
                    "raw": raw,
                    "prompt": prompt,
                    "prompt_sha256": identity["prompt_sha256"],
                    "elapsed": elapsed,
                    "metadata": dict(metadata),
                }
                seal(path, value, identity)
                self.observed.append({**value, "reused_within_run": False})
                return raw, elapsed, dict(metadata)
            except IntegrityError:
                raise
            except (
                TimeoutError,
                socket.timeout,
                urllib.error.URLError,
                ConnectionError,
                TransportError,
                ValueError,
                OSError,
            ) as error:
                if attempt == 2:
                    raise TransportError(str(error)) from error
                time.sleep(5 * (attempt + 1))


def inspect_models(base, config, locked_models=None):
    actual_version = api(base, "version").get("version")
    if actual_version != config["ollama_version"]:
        raise IntegrityError(
            f"Expected Ollama {config['ollama_version']}, found {actual_version}"
        )
    tags = {r["name"]: r for r in api(base, "tags")["models"]}
    result = {}
    for name in config["models"]:
        if name not in tags:
            raise IntegrityError(f"Model unavailable: {name}")
        details = api(base, "show", {"model": name})
        result[name] = {
            "digest": tags[name]["digest"],
            "parameters": details.get("parameters"),
            "template": details.get("template"),
        }
        if locked_models:
            expected = locked_models[name]
            normalize = lambda value: (
                sorted(value.splitlines()) if value is not None else None
            )
            if (
                result[name]["digest"] != expected["digest"]
                or result[name]["template"] != expected["template"]
                or normalize(result[name]["parameters"])
                != normalize(expected["parameters"])
            ):
                raise IntegrityError(f"Model identity or configuration changed: {name}")
    return result


def prepare_model(base, model, config):
    for loaded in api(base, "ps")["models"]:
        if loaded["name"] != model:
            if loaded["name"] not in config["models"]:
                raise IntegrityError("An unrelated model is loaded on this server")
            api(
                base,
                "generate",
                {"model": loaded["name"], "keep_alive": 0, "stream": False},
                timeout=config["settings"]["timeout"],
            )
    settings = config["settings"]
    options = {
        k: settings[k] for k in ("num_ctx", "num_thread") if settings.get(k) is not None
    }
    api(
        base,
        "generate",
        {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": settings["keep_alive"],
            "options": options,
        },
        timeout=settings["timeout"],
    )
