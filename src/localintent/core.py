"""Prompt assembly, method routing, validation and diagnostic scoring."""

import argparse

import csv

import json

import platform

import statistics

import subprocess

import time

import urllib.error

import urllib.request

from .schema import (
    action_parameter_correct,
    canonicalize_output,
    detect_language,
    extract_json_payload,
    is_rule_output,
    load_prompt,
    language_consistency_correct,
    generation_platform_context,
    normalize_intent_result,
    normalization_change_details,
    normalization_diagnostic_details,
    output_format_valid,
    output_mode_correct,
    parameters_match,
    result_device_action_set,
    result_device_set,
    raw_parameter_completeness_details,
    routing_platform_context,
    twostage_routing_platform_context,
    rule_intent_understanding_correct,
)

DEFAULT_NUM_CTX = 4096

LOCALINTENT_PROTOCOL = "localintent"

TWOSTAGE_GENERIC_PROTOCOL = "two_stage"

LOCALINTENT_PROMPTS = {
    "gate": "localintent/routing",
    "ordinary": "localintent/ordinary",
    "rule": "localintent/rule",
}

LOCALINTENT_PROMPT_SHA256 = {
    "gate": "fb154c155aa18e2a9d1d452961c52cc1732698402f6bf0bd2d5b4e481025f4bc",
    "ordinary": "4dd807a92be2a7cd313c415efdba6ddb20d419cf617f54177fb4009085aff298",
    "rule": "0838313b98d5a7b62796fbbd4cf90d05aedf0512ff961142a5ea3b3b09eb620d",
}

JSON_ONLY_SUFFIX = (
    "\n\nReturn only valid JSON. "
    "Do not include explanations, comments, markdown, or code fences."
)

GENERATION_SETTINGS = {
    "num_ctx": DEFAULT_NUM_CTX,
    "temperature": None,
    "top_p": None,
    "top_k": None,
    "seed": None,
}

FUTURE_CUES = [
    "whenever",
    "every time",
    "in the future",
    "from now on",
    "automatically",
    "next time",
    "never let",
    "don't let this happen again",
    "don't ever let",
    "if it gets like this again",
    "if it is this bad again",
    "just handle it for me next time",
    "just handle it for me when this happens again",
    "keep it quiet in the future",
    "keep the house sealed if it's like this",
    "do something about it whenever",
    "从今以后",
    "以后",
    "每次",
    "一直",
]


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_model_input(record, context_kind="generation", outcome=None):
    if context_kind == "routing":
        context = routing_platform_context(
            record["input"]["current_state"],
            record["input"]["timestamp"],
        )
    elif context_kind == "generation":
        context = generation_platform_context(
            record["input"]["current_state"],
            record["input"]["timestamp"],
            outcome,
        )
    else:
        raise ValueError(f"Unknown context kind: {context_kind}")
    return {
        "userInstruction": record["input"]["userInstruction"],
        **context,
    }


def build_prompt(prompt_text, record, context_kind="generation", outcome=None):
    model_input = build_model_input(record, context_kind, outcome)
    return prompt_text + JSON_ONLY_SUFFIX + f"\n\nInput:\n{compact_json(model_input)}"


def build_localintent_input(record):
    """Build the instruction, state and timestamp used by LocalIntent."""
    return {
        "userInstruction": record["input"]["userInstruction"],
        "current_state": record["input"]["current_state"],
        "timestamp": record["input"]["timestamp"],
    }


def build_localintent_prompt(prompt_text, record):
    """Assemble the LocalIntent prompt with its original whitespace."""
    return (
        prompt_text
        + JSON_ONLY_SUFFIX
        + "\n\nInput:\n"
        + json.dumps(
            build_localintent_input(record),
            ensure_ascii=False,
            indent=2,
        )
    )


def build_twostage_stage1_prompt(prompt_text, record):
    local_context = twostage_routing_platform_context(
        record["input"]["current_state"],
        record["input"]["timestamp"],
    )
    return (
        prompt_text
        + f"\n\nUser request: {record['input']['userInstruction']}"
        + f"\nLocal context:\n{compact_json(local_context)}"
        + "\nOutput:"
    )


def parse_twostage_stage1_outcome(raw_response):
    allowed_outcomes = {"command", "rule", "clarification", "rejection"}
    outcome = raw_response.strip().lower()
    if outcome in allowed_outcomes:
        return outcome, True, ""
    return (
        "clarification",
        False,
        (
            "invalid_stage1_outcome: expected exactly one of Command, Rule, "
            f"Clarification, Rejection; received {raw_response!r}"
        ),
    )


def call_ollama(model, prompt, ollama_url, timeout):
    request_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": -1,
    }
    explicit_options = {
        key: value for key, value in GENERATION_SETTINGS.items() if value is not None
    }
    if explicit_options:
        request_payload["options"] = explicit_options
    payload = json.dumps(request_payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    latency = time.time() - started
    metadata = {
        "prompt_characters": len(prompt),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "done_reason": body.get("done_reason"),
        "num_ctx": GENERATION_SETTINGS["num_ctx"],
        "elapsed_time_sec": latency,
    }
    return body.get("response", ""), latency, metadata


def temporal_fallback(user_instruction):
    lowered = user_instruction.lower()
    return "rule" if any(cue in lowered for cue in FUTURE_CUES) else "ordinary"


def route_localintent(
    record,
    model,
    ollama_url,
    timeout,
    tolerate_invalid_final=False,
):
    """Route between ordinary and persistent-rule generation.

    LocalIntent uses indented instruction/state JSON. The generic baseline uses
    compact, outcome-specific capability context. These are distinct methods.
    """
    gate_prompt_text = load_prompt(LOCALINTENT_PROMPTS["gate"])
    ordinary_prompt_text = load_prompt(LOCALINTENT_PROMPTS["ordinary"])
    rule_prompt_text = load_prompt(LOCALINTENT_PROMPTS["rule"])

    gate_prompt = build_localintent_prompt(gate_prompt_text, record)
    gate_raw_response, gate_latency, gate_call = call_ollama(
        model, gate_prompt, ollama_url, timeout
    )
    gate_call["stage"] = "routing"

    try:
        gate_payload = extract_json_payload(gate_raw_response)
        route_mode = str(gate_payload.get("mode", "")).strip().lower()
    except (ValueError, json.JSONDecodeError, TypeError, AttributeError):
        route_mode = ""

    gate_fallback_used = route_mode not in {"ordinary", "rule"}
    if gate_fallback_used:
        route_mode = temporal_fallback(record["input"]["userInstruction"])

    chosen_prompt = rule_prompt_text if route_mode == "rule" else ordinary_prompt_text
    final_prompt = build_localintent_prompt(chosen_prompt, record)
    final_raw_response, final_latency, final_call = call_ollama(
        model, final_prompt, ollama_url, timeout
    )
    final_call["stage"] = "generation"
    try:
        final_payload = extract_json_payload(final_raw_response)
    except (ValueError, json.JSONDecodeError, TypeError, AttributeError):
        if not tolerate_invalid_final:
            raise
        final_payload = None

    return {
        "localintent_protocol": LOCALINTENT_PROTOCOL,
        "model_input": build_localintent_input(record),
        "prompt_names": dict(LOCALINTENT_PROMPTS),
        "prompt_sha256": dict(LOCALINTENT_PROMPT_SHA256),
        "route_mode": route_mode,
        "gate_fallback_used": gate_fallback_used,
        "gate_raw_response": gate_raw_response,
        "final_raw_response": final_raw_response,
        "final_payload": final_payload,
        "latency_seconds": gate_latency + final_latency,
        "ollama_calls": [gate_call, final_call],
    }


def validate_model_output(raw_response, current_state):
    """Run the shared parser, normalizer, and automatic checker."""
    try:
        payload = extract_json_payload(raw_response)
    except (ValueError, json.JSONDecodeError, TypeError, AttributeError):
        diagnostic = {
            "code": "json_parse_failed",
            "path": "$",
            "message": "The response is not valid JSON. Return exactly one valid JSON object with no surrounding text.",
        }
        return {
            "raw_payload": None,
            "output": None,
            "parse_success": False,
            "checker_passed": False,
            "checker_errors": ["json_parse_failed"],
            "checker_diagnostics": [diagnostic],
            "checker_messages": [diagnostic["message"]],
            "raw_parameter_audit": {
                "applicable": False,
                "complete": None,
                "missing": [],
            },
            "normalization_changed_output": False,
            "normalization_changes": [],
        }

    checker_diagnostics = normalization_diagnostic_details(payload, current_state)
    checker_errors = sorted({item["code"] for item in checker_diagnostics})
    raw_parameter_audit = raw_parameter_completeness_details(payload)
    normalization_changes = []
    try:
        payload_copy = json.loads(json.dumps(payload, ensure_ascii=False))
        output = canonicalize_output(
            normalize_intent_result(payload_copy, current_state)
        )
        normalization_changes = normalization_change_details(payload, output)
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        code = f"normalization_failed:{type(exc).__name__}"
        checker_errors.append(code)
        checker_diagnostics.append(
            {
                "code": code,
                "path": "$",
                "message": f"The output could not be normalized because of {type(exc).__name__}; follow the shared output schema exactly.",
            }
        )
        output = None

    if output is not None and not output_format_valid(output):
        checker_errors.append("output_format_invalid")
        checker_diagnostics.append(
            {
                "code": "output_format_invalid",
                "path": "$",
                "message": "The normalized output still violates the shared backend output schema. Follow the output_schemas in local context exactly.",
            }
        )

    checker_errors = sorted(set(checker_errors))
    checker_diagnostics = sorted(
        checker_diagnostics,
        key=lambda item: (item["code"], item.get("path", ""), item["message"]),
    )
    return {
        "raw_payload": payload,
        "output": output,
        "parse_success": True,
        "checker_passed": output is not None and not checker_errors,
        "checker_errors": checker_errors,
        "checker_diagnostics": checker_diagnostics,
        "checker_messages": [item["message"] for item in checker_diagnostics],
        "raw_parameter_audit": raw_parameter_audit,
        "normalization_changed_output": bool(normalization_changes),
        "normalization_changes": normalization_changes,
    }


def route_two_stage(record, model, ollama_url, timeout):
    stage1_prompt_text = load_prompt("two_stage/routing")
    stage2_prompt_names = {
        "command": "two_stage/command",
        "rule": "two_stage/rule",
        "clarification": "two_stage/clarification",
        "rejection": "two_stage/rejection",
    }

    stage1_prompt = build_twostage_stage1_prompt(stage1_prompt_text, record)
    stage1_raw_response, stage1_latency, stage1_call = call_ollama(
        model, stage1_prompt, ollama_url, timeout
    )
    stage1_call["stage"] = "stage1"
    stage1_outcome, stage1_response_valid, stage1_error = parse_twostage_stage1_outcome(
        stage1_raw_response
    )

    stage2_prompt_text = load_prompt(stage2_prompt_names[stage1_outcome])
    stage2_prompt = build_prompt(stage2_prompt_text, record, outcome=stage1_outcome)
    stage2_raw_response, stage2_latency, stage2_call = call_ollama(
        model, stage2_prompt, ollama_url, timeout
    )
    stage2_call["stage"] = "stage2"
    stage2_check = validate_model_output(
        stage2_raw_response,
        record["input"]["current_state"],
    )

    return {
        "method_protocol": TWOSTAGE_GENERIC_PROTOCOL,
        "route_mode": stage1_outcome,
        "stage1_outcome": stage1_outcome,
        "stage1_response_valid": stage1_response_valid,
        "stage1_error": stage1_error,
        "gate_raw_response": stage1_raw_response,
        "final_raw_response": stage2_raw_response,
        "final_payload": stage2_check["output"],
        "stage2_parse_success": stage2_check["parse_success"],
        "checker_passed": stage2_check["checker_passed"],
        "checker_errors": stage2_check["checker_errors"],
        "checker_diagnostics": stage2_check["checker_diagnostics"],
        "checker_messages": stage2_check["checker_messages"],
        "raw_parameter_audit": stage2_check["raw_parameter_audit"],
        "normalization_changed_output": stage2_check["normalization_changed_output"],
        "normalization_changes": stage2_check["normalization_changes"],
        "latency_seconds": stage1_latency + stage2_latency,
        "stage1_latency_seconds": stage1_latency,
        "stage2_latency_seconds": stage2_latency,
        "ollama_calls": [stage1_call, stage2_call],
    }


def compute_paper_scores(prediction, reference, user_instruction):
    if prediction is None:
        return {key: 0 for key in ["IU", "DI", "CH", "APC", "OFC", "LC"]}

    canonical_prediction = canonicalize_output(prediction)
    canonical_reference = canonicalize_output(reference)
    if is_rule_output(canonical_reference):
        iu = rule_intent_understanding_correct(
            canonical_prediction, canonical_reference
        )
        ch = output_mode_correct(canonical_prediction, canonical_reference)
    else:
        iu = result_device_action_set(canonical_prediction) == result_device_action_set(
            canonical_reference
        )
        ch = canonical_prediction.get("needsClarification") == canonical_reference.get(
            "needsClarification"
        )

    return {
        "IU": int(iu),
        "DI": int(
            result_device_set(canonical_prediction)
            == result_device_set(canonical_reference)
        ),
        "CH": int(ch),
        "APC": int(action_parameter_correct(canonical_prediction, canonical_reference)),
        "OFC": int(output_format_valid(canonical_prediction)),
        "LC": int(
            language_consistency_correct(
                canonical_prediction, detect_language(user_instruction)
            )
        ),
    }
