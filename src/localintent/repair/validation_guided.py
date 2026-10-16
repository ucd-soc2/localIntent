"""Validation-guided, single-call repair used in the paper experiment."""

from __future__ import annotations
import json
import re
from pathlib import Path
from .. import core as base
from .common import action_identities, outcome_family, structured_diagnostics

PROTOCOL_ID = "validation_guided"
PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts/repair/validation_guided.txt"
)


def _actions(output: dict | None):
    if not isinstance(output, dict):
        return []
    if isinstance(output.get("rule"), dict) and isinstance(
        output["rule"].get("action"), dict
    ):
        return [("$.rule.action", output["rule"]["action"])]
    return [
        (f"$.result[{i}]", item)
        for i, item in enumerate(output.get("result", []))
        if isinstance(item, dict)
    ]


def semantic_diagnostics(output: dict | None, request: str) -> list[dict]:
    """Detect only explicit action/parameter contradictions without a gold output.

    Rules intentionally target parameter values, not device/outcome selection. They
    are auditable, use no reference/scorer, and are conservative by construction.
    """
    text = request.lower()
    diagnostics: list[dict] = []
    for path, action in _actions(output):
        device, verb = action.get("deviceId"), action.get("action")
        params = (
            action.get("parameters")
            if isinstance(action.get("parameters"), dict)
            else {}
        )

        def add(key, expected, reason):
            if params.get(key) != expected:
                diagnostics.append(
                    {
                        "code": "semantic_parameter_target_mismatch",
                        "path": f"{path}.parameters.{key}",
                        "received": params.get(key),
                        "expected": expected,
                        "reason": reason,
                    }
                )

        # Direct post-action invariants: closing/opening must reach the named end state.
        if (
            device in {"smartWindow", "smartCurtains"}
            and verb == "turn_off"
            and "openPercentage" in params
        ):
            add(
                "openPercentage",
                0,
                "turn_off must close the opening rather than retain its current percentage",
            )
        if (
            device in {"smartWindow", "smartCurtains"}
            and verb == "turn_on"
            and re.search(r"\b(open|fresh air|ventilat)", text)
            and "openPercentage" in params
        ):
            add(
                "openPercentage",
                100,
                "an explicit open/ventilation request requires an open target state",
            )
        # Strong insufficiency/worsening language must not preserve a neutral purifier setting.
        if (
            device == "airPurifier"
            and verb == "turn_on"
            and re.search(r"heavy|uncomfortable|air feels bad|bad in here|dizzy", text)
            and "fanSpeed" in params
        ):
            add(
                "fanSpeed",
                "high",
                "strong air-quality discomfort requires a high purification target",
            )
        # Very low-visibility requests need a non-neutral light target.
        if (
            device == "light"
            and verb == "turn_on"
            and re.search(r"barely see|can.?t see|too dark|can.?t see very well", text)
            and "brightness" in params
        ):
            if (
                not isinstance(params.get("brightness"), (int, float))
                or params["brightness"] < 4
            ):
                diagnostics.append(
                    {
                        "code": "semantic_parameter_target_mismatch",
                        "path": f"{path}.parameters.brightness",
                        "received": params.get("brightness"),
                        "expected": 4,
                        "reason": "very low visibility requires a high light-brightness target",
                    }
                )
        # Thermal comfort: a request to become warmer is incompatible with cooling.
        if (
            device == "ac"
            and verb == "turn_on"
            and re.search(r"colder|warmer|chilly|cold", text)
        ):
            add("mode", "heat", "a cold/warmer request requires heating mode")
            if "temperature" in params and (
                not isinstance(params.get("temperature"), (int, float))
                or params["temperature"] < 26
            ):
                diagnostics.append(
                    {
                        "code": "semantic_parameter_target_mismatch",
                        "path": f"{path}.parameters.temperature",
                        "received": params.get("temperature"),
                        "expected": 26,
                        "reason": "a cold/warmer request requires a warmer target temperature",
                    }
                )
        # Strong cleaning, bathing, and respiratory requests have unambiguous device-mode targets.
        if (
            device == "robotVacuum"
            and verb == "turn_on"
            and re.search(r"floor.*(?:dirty|dusty)|dirty.*floor|rug", text)
            and "cleaningMode" in params
        ):
            add(
                "cleaningMode",
                "turbo",
                "a strongly dirty floor requires turbo cleaning mode",
            )
        if (
            device == "waterHeater"
            and verb == "turn_on"
            and re.search(r"shower|bath|soak|wash up", text)
        ):
            add(
                "mode",
                "keep_warm",
                "a shower/bath request requires a ready hot-water mode",
            )
            if "temperature" in params and params.get("temperature") != 60:
                diagnostics.append(
                    {
                        "code": "semantic_parameter_target_mismatch",
                        "path": f"{path}.parameters.temperature",
                        "received": params.get("temperature"),
                        "expected": 60,
                        "reason": "a shower/bath request requires a ready hot-water target temperature",
                    }
                )
        if (
            device == "airPurifier"
            and verb == "turn_on"
            and re.search(r"sneez|cough|smells dusty|air.*dead", text)
        ):
            add(
                "fanSpeed",
                "high",
                "respiratory air-quality discomfort requires high purification",
            )
            add(
                "mode",
                "manual",
                "respiratory air-quality discomfort requires an active manual purification mode",
            )
        if (
            device == "light"
            and verb == "turn_on"
            and re.search(r"straining.*see|hard to see.*book|dark.*trip", text)
            and "brightness" in params
        ):
            if (
                not isinstance(params.get("brightness"), (int, float))
                or params["brightness"] < 5
            ):
                diagnostics.append(
                    {
                        "code": "semantic_parameter_target_mismatch",
                        "path": f"{path}.parameters.brightness",
                        "received": params.get("brightness"),
                        "expected": 5,
                        "reason": "reading difficulty or trip risk requires the highest light-brightness target",
                    }
                )
        # Explicit numerical temperature instruction is an unambiguous runtime target.
        match = re.search(r"(?:to|at)\s*(\d{2})\s*(?:°|degrees?|c)\b", text)
        if (
            device == "waterHeater"
            and verb == "turn_on"
            and match
            and "temperature" in params
        ):
            add(
                "temperature",
                int(match.group(1)),
                "the request explicitly specifies the water-heater temperature",
            )
    return diagnostics


def build_repair_prompt(
    record: dict,
    initial_output: dict | None,
    structural: list[dict],
    semantic: list[dict],
    route_mode: str | None,
) -> str:
    context = base.build_model_input(record, outcome=route_mode)
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{REQUEST}", record["input"]["userInstruction"])
        .replace("{CONTEXT}", json.dumps(context, ensure_ascii=False, indent=2))
        .replace(
            "{INITIAL_OUTPUT}", json.dumps(initial_output, ensure_ascii=False, indent=2)
        )
        .replace(
            "{STRUCTURAL_DIAGNOSTICS}",
            json.dumps(
                structured_diagnostics(structural), ensure_ascii=False, indent=2
            ),
        )
        .replace(
            "{SEMANTIC_DIAGNOSTICS}", json.dumps(semantic, ensure_ascii=False, indent=2)
        )
    )


def candidate_acceptable(
    initial: dict | None,
    candidate: dict | None,
    structural: list[dict],
    semantic: list[dict],
) -> tuple[bool, str]:
    if not isinstance(candidate, dict):
        return False, "missing_candidate"
    if initial is None:
        return True, "accepted_no_initial_object"
    schema_codes = {
        "json_parse_failed",
        "outcome_schema_conflict",
        "output_format_invalid",
    }
    codes = {item.get("code") for item in structural if isinstance(item, dict)}
    if outcome_family(initial) != outcome_family(candidate) and not codes.intersection(
        schema_codes
    ):
        return False, "outcome_changed_without_structural_diagnostic"
    if action_identities(initial) != action_identities(candidate):
        return False, "action_identity_changed_without_authorization"
    return True, "accepted_semantic_parameter_repair"


import time


def execute(record: dict, model: str, ollama_url: str, timeout: int) -> dict:
    start = time.perf_counter_ns()
    local = base.route_localintent(
        record, model, ollama_url, timeout, tolerate_invalid_final=True
    )
    state = record["input"]["current_state"]
    initial_raw = local["final_raw_response"]
    initial = base.validate_model_output(initial_raw, state)
    structural = initial["checker_diagnostics"]
    semantic = semantic_diagnostics(
        initial.get("output"), record["input"]["userInstruction"]
    )
    triggered = bool(structural or semantic)
    candidate_raw = None
    candidate = None
    accepted = False
    reason = "repair_not_triggered"
    latency = 0.0
    final = initial
    calls = list(local["ollama_calls"])
    if len(calls) >= 2:
        calls[1]["stage"] = "initial_generation"
    prompt = None
    if triggered:
        prompt = build_repair_prompt(
            record, initial.get("output"), structural, semantic, local.get("route_mode")
        )
        candidate_raw, latency, call = base.call_ollama(
            model, prompt, ollama_url, timeout
        )
        call["stage"] = "semantic_repair"
        calls.append(call)
        candidate = base.validate_model_output(candidate_raw, state)
        if candidate["checker_passed"]:
            accepted, reason = candidate_acceptable(
                initial.get("output"), candidate.get("output"), structural, semantic
            )
            if accepted:
                final = candidate
        else:
            reason = "repair_candidate_failed_checker"
    return {
        "protocol": PROTOCOL_ID,
        "route_mode": local.get("route_mode"),
        "gate_raw_response": local.get("gate_raw_response"),
        "initial_raw_output": initial_raw,
        "initial_raw_output": initial_raw,
        "initial": initial,
        "structural_diagnostics": structural,
        "semantic_diagnostics": semantic,
        "repair_triggered": triggered,
        "repair_prompt": prompt,
        "candidate_raw_output": candidate_raw,
        "candidate": candidate,
        "repair_accepted": accepted,
        "repair_succeeded": triggered and accepted,
        "acceptance_reason": reason,
        "final": final,
        "final_raw_output": candidate_raw if accepted else initial_raw,
        "fallback_to_initial": triggered and not accepted,
        "localintent_latency_seconds": local["latency_seconds"],
        "repair_latency_seconds": latency,
        "end_to_end_latency_ns": time.perf_counter_ns() - start,
        "ollama_calls": calls,
    }
