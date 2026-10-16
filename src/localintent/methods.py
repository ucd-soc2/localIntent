"""One-call, generic two-stage, and outcome-specific generation methods."""

from __future__ import annotations

import time
from . import core
from .schema import load_prompt


def execute(record, method, model, url, timeout):
    if method == "localintent":
        local = core.route_localintent(
            record, model, url, timeout, tolerate_invalid_final=True
        )
        raw = local["final_raw_response"]
        return (
            core.validate_model_output(raw, record["input"]["current_state"]),
            local,
            raw,
        )
    if method == "two_stage":
        local = core.route_two_stage(record, model, url, timeout)
        raw = local["final_raw_response"]
        return (
            core.validate_model_output(raw, record["input"]["current_state"]),
            local,
            raw,
        )
    if method == "monolithic":
        prompt = core.build_prompt(load_prompt("monolithic"), record)
        raw, elapsed, call = core.call_ollama(model, prompt, url, timeout)
        call["stage"] = "monolithic_generation"
        return (
            core.validate_model_output(raw, record["input"]["current_state"]),
            {
                "route_mode": "monolithic",
                "ollama_calls": [call],
                "latency_seconds": elapsed,
            },
            raw,
        )
    raise ValueError(f"Unknown method: {method}")
