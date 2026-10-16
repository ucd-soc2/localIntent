"""Grounded repair with command-family and action-completeness checks."""

import copy
import json
import re
from .. import core as base
from . import parameters

PROTOCOL_ID = "grounded"

outcome_family = parameters.outcome_family

action_identities = parameters.action_identities

_ALIASES = {
    "tv": r"(?:tv|television)",
    "light": r"(?:light|lights|lamp)",
    "ac": r"(?:ac|air[ -]conditioner|cooling)",
    "humidifier": r"humidifier",
    "coffeeMachine": r"coffee machine",
    "smartCurtains": r"curtains?",
    "robotVacuum": r"(?:robot vacuum|vacuum)",
    "airPurifier": r"(?:air purifier|air cleaner|purifier)",
    "smartWindow": r"window",
    "waterHeater": r"water heater",
}

_VERBS = r"turn|switch|start|activate|run|stop|halt|shut|close|open|cool|warm|heat|set|adjust"

_PREFIX = r"^(?:(?:please\s+)|(?:(?:can|could|would) you\s+(?:please\s+)?))?"


def _reject_reason(text):
    patterns = {
        "conditional_future_or_delayed": r"\b(?:if|when|whenever|unless|until|once|after|before|provided|assuming|every|each|always|automatically|automatic|future|tomorrow|later|schedule\w*|next time|from now on|as soon as|in case|at night|tonight|this evening|soon|again)\b|\b(?:in|within)\s+(?:\d+|a few|some|one|two|three|five|ten|a quarter|a half|half)\s+(?:seconds?|minutes?|hours?|days?|of an hour)\b|\b(?:at|by)\s+(?:\d{1,2}:\d{2}|noon|midnight|dawn|dusk|sunset|sunrise)\b|\bhalf an hour\b",
        "negative_or_uncertain": r"\b(?:do not|don.t|never|avoid|not yet|not now|not sure|not decided|not chosen|not certain|not selected|haven.t decided|haven.t chosen|have not decided|have not chosen|have not selected|need to decide|need to choose|unsure|undecided|whether|maybe|perhaps|either|instead of|rather than|without starting|considering|not ready|not a new request)\b",
        "reported_hypothetical_or_question": r'\b(?:yesterday|used to|said|say|quoted?|example|hypothetical|pretend|suppose|imagine|would happen|how do|how can|is it|is the|can it)\b|["“”]',
        "unsupported_or_emergency": r"\b(?:oven|front door|door lock|dishwasher|washing machine|radiator|ceiling fan|toaster|blinds|telephone|call|order|fetch|emergency|chest|short of breath|medical)\b",
    }
    for reason, pattern in patterns.items():
        if re.search(pattern, text):
            return reason
    if re.search(r"(?:^|\s)'[^']+'(?:\s|[.,!?]|$)", text):
        return "quoted_instruction"
    alternatives = re.sub(
        r"\bwithout changing\s+(?:(?:its|the|current|existing|saved)\s+)*channel\s+or\s+volume\b",
        "",
        text,
    )
    if re.search(r"\bor\b", alternatives):
        return "alternative_action_or_parameter"
    return None


def _named(text):
    return [
        device
        for device, pattern in _ALIASES.items()
        if re.search(r"\b" + pattern + r"\b", text)
    ]


def _pair(device, action, basis, clause, mode=None):
    result = {"deviceId": device, "action": action, "basis": basis, "clause": clause}
    if mode:
        result["mode"] = mode
    return result


def _explicit_clause(clause):
    """Parse a whole imperative clause; unrecognized list members reject it."""
    text = re.sub(_PREFIX, "", clause).strip()
    thermal = re.fullmatch(
        r"(cool|warm|heat)\s+(?:the |this |my )?(?:room|it|house)(?:\s+(?:now|right now))?(?:\s+(?:to|at)\s+\d+\s*(?:degrees?|celsius|°c))?",
        text,
    )
    if thermal:
        pair = _pair(
            "ac",
            "turn_on",
            "explicit_thermal_remedy",
            clause,
            "cool" if thermal[1] == "cool" else "heat",
        )
        target = re.search(r"\b(?:to|at)\s+(\d+)\s*(?:degrees?|celsius|°c)", text)
        if target:
            if not 16 <= int(target[1]) <= 30:
                return None
            pair["temperature"] = int(target[1])
        return [pair]
    verb = re.match(
        r"(?:(turn|switch)\s+(on|off)|(start|activate|run|stop|halt|close|open|shut off))\s+(.+)",
        text,
    )
    if not verb:
        # "Turn the AC on" has a different word order.
        reverse = re.fullmatch(
            r"(?:turn|switch)\s+(?:the |my |this )?(.+?)\s+(on|off)(?:\s+now)?", text
        )
        if not reverse:
            return None
        verb_action = "turn_on" if reverse[2] == "on" else "turn_off"
        body = reverse[1]
    else:
        body = verb[4]
        verb_action = (
            "turn_off"
            if (verb[2] == "off" or verb[3] in ("stop", "halt", "close", "shut off"))
            else "turn_on"
        )
    # Purpose follows the complete list, never supplies an additional action.
    body = re.split(r"\s+(?:so (?:i|we)|because|to help)\b", body, maxsplit=1)[0]
    body = re.sub(r"\s+(?:right now|now|right away|at the moment)$", "", body)
    members = re.split(r"\s*,\s*|\s+and\s+", body)
    pairs = []
    for member in members:
        member = re.sub(r"^(?:the|my|this)\s+", "", member.strip()).strip()
        matches = [d for d, p in _ALIASES.items() if re.fullmatch(p, member)]
        if len(matches) != 1:
            return None
        device = matches[0]
        if (
            verb
            and verb[3] in ("close", "open")
            and device not in ("smartWindow", "smartCurtains")
        ):
            return None
        pairs.append(_pair(device, verb_action, "explicit_device_action", clause))
    return pairs or None


def action_inventory(request, state):
    """Certify a complete action inventory; deliberately abstain on ambiguity.

    A direct imperative may contain several devices and one implicit thermal
    action. Unparsed directives, unknown list members, and conflicting actions
    veto certification. Narrow implicit cases require both strong semantics and
    relevant state; mild discomfort cannot override clarification.
    """
    text = request.lower().strip()
    reason = _reject_reason(text)
    if reason:
        return {"eligible": False, "reason": reason}
    pairs = []
    # Split only at a conjunction followed by another action verb, preserving
    # "TV, light and air purifier" as one explicitly parsed list.
    clauses = re.split(
        r"[;!?]|\.(?!\d)|\s+and\s+(?=(?:please\s+)?(?:"
        + _VERBS
        + r")\b)|,\s*(?=(?:please\s+)?(?:"
        + _VERBS
        + r")\b)",
        text,
    )
    for clause in clauses:
        clause = clause.strip(" ,")
        if not clause:
            continue
        # A descriptive introduction may precede a polite directive.
        parts = re.split(r";|,\s*(?=please\b)", clause)
        for part in parts:
            part = part.strip()
            if re.search(_PREFIX + r"(?:" + _VERBS + r")\b", part):
                parsed = _explicit_clause(part)
                if parsed is None:
                    return {
                        "eligible": False,
                        "reason": "unparsed_action_or_parameter_clause",
                    }
                pairs.extend(parsed)
            elif re.search(
                r"\b(?:please|i need|i want|i would like|i also need)\b.*\b(?:"
                + _VERBS
                + r")\b",
                part,
            ):
                return {"eligible": False, "reason": "unparsed_request_clause"}
            elif not re.match(
                r"^(?:i\b|my\b|the\b|this\b|there\b|it\b|its\b|that\b)", part
            ):
                return {"eligible": False, "reason": "unparsed_additional_clause"}
    # Implicit source-specific shutdown: an active robot vacuum is named and
    # unwanted noise is preventing rest, rather than general ambient noise.
    if (
        re.search(r"\brobot vacuum\b", text)
        and re.search(r"\b(?:rumbl\w*|nois\w*|loud)\b", text)
        and re.search(r"\b(?:quiet|silence|rest|conversation|sleep)\b", text)
        and state.get("robotVacuum", {}).get("status") == "on"
    ):
        pairs.append(
            _pair("robotVacuum", "turn_off", "implicit_active_noise_source", text)
        )
    if not pairs:
        # A daylight alternative stays uncertain. Never use dim alone.
        poor = re.search(
            r"\b(?:hard to see|cannot see|can.t see|barely see|need (?:a little )?more light)\b",
            text,
        )
        unambiguous_light = (
            re.search(
                r"\b(?:no daylight|no usable daylight|no sunlight|nighttime|hallway|reading|threading|stumble)\b",
                text,
            )
            or state.get("smartCurtains", {}).get("openPercentage") == 100
        )
        if (
            poor
            and unambiguous_light
            and not re.search(r"\b(?:glare|glaring|too bright)\b", text)
        ):
            pairs.append(
                _pair(
                    "light",
                    "turn_on",
                    "implicit_visibility_with_no_daylight_alternative",
                    text,
                )
            )
        elif (
            re.search(r"\b(?:very dry air|air feels very dry|parched air)\b", text)
            and isinstance(state.get("humiditySensor"), (int, float))
            and state["humiditySensor"] < 50
        ):
            pairs.append(
                _pair(
                    "humidifier", "turn_on", "implicit_strong_dry_air_with_state", text
                )
            )
        elif re.search(
            r"\b(?:uncomfortably hot|too hot|too chilly|shiver\w*)\b", text
        ) and not re.search(
            r"\b(?:a little|slightly|warm enough|although|even though)\b", text
        ):
            hot = bool(re.search(r"\b(?:uncomfortably hot|too hot)\b", text))
            cold = bool(re.search(r"\b(?:too chilly|shiver\w*)\b", text))
            if hot != cold and not re.search(
                r"\b(?:damp|dry|stuffy|glare|dusty|noisy)\b", text
            ):
                pairs.append(
                    _pair(
                        "ac",
                        "turn_on",
                        "implicit_strong_present_thermal_need",
                        text,
                        "cool" if hot else "heat",
                    )
                )
    if not pairs:
        return {"eligible": False, "reason": "no_unique_current_action"}
    unique = {}
    for pair in pairs:
        device = pair["deviceId"]
        if device in unique and (
            unique[device]["action"] != pair["action"]
            or unique[device].get("mode") != pair.get("mode")
        ):
            return {"eligible": False, "reason": "conflicting_device_actions"}
        unique.setdefault(device, pair)
    pairs = list(unique.values())
    # A separately named device cannot silently disappear from certification.
    if set(_named(text)) - set(unique):
        return {"eligible": False, "reason": "named_device_without_grounded_action"}
    if any(not isinstance(state.get(p["deviceId"]), dict) for p in pairs):
        return {"eligible": False, "reason": "device_state_unavailable"}
    return {
        "eligible": True,
        "pairs": pairs,
        "identities": [(p["deviceId"], p["action"]) for p in pairs],
        "reason": "complete_grounded_current_action_inventory",
    }


def _identity_set(output):
    return set(action_identities(output))


def _scoped_actions(request, state, output, evidence):
    """Apply grounded fields in device clauses, never across devices."""
    result = copy.deepcopy(output)
    specs = base.build_model_input(
        {
            "input": {
                "userInstruction": request,
                "current_state": state,
                "timestamp": "00:00:00",
            }
        }
    )["capability_registry"]["device_parameters"]
    pair_map = {(p["deviceId"], p["action"]): p for p in evidence["pairs"]}
    for _, action in parameters._actions(result):
        identity = (action.get("deviceId"), action.get("action"))
        pair = pair_map.get(identity)
        if not pair:
            continue
        device = identity[0]
        clause = pair["clause"]
        params = action["parameters"]
        if pair["basis"] == "explicit_device_action":
            # These parsed clauses contain no settings: pure switch preserves
            # all schema fields; closing has the explicit zero postcondition.
            for field in specs[device]:
                value = state[device].get(field)
                if parameters._schema_field_valid(value, specs[device][field]):
                    params[field] = copy.deepcopy(value)
            if device in ("smartWindow", "smartCurtains") and identity[1] == "turn_off":
                params["openPercentage"] = 0
            if device in ("smartWindow", "smartCurtains") and identity[1] == "turn_on":
                params["openPercentage"] = 100
        elif pair["basis"] == "implicit_active_noise_source":
            params.update(
                {
                    k: copy.deepcopy(state[device][k])
                    for k in specs[device]
                    if k in state[device]
                }
            )
        elif pair.get("mode"):
            params["mode"] = pair["mode"]
        if "temperature" in pair:
            params["temperature"] = pair["temperature"]
        single = {
            "needsClarification": False,
            "message": result.get("message", ""),
            "result": [action],
        }
        for op in parameters.repair_plan(clause, state, single):
            parameters._set(single, tuple(op["path"]), op["target"])
    return result


def _pure_switch_candidate(state, evidence):
    """Materialize fully specified switches from the unchanged state policy."""
    if not all(
        p["basis"] in ("explicit_device_action", "implicit_active_noise_source")
        for p in evidence["pairs"]
    ):
        return None

    specs = base.build_model_input(
        {
            "input": {
                "userInstruction": "",
                "current_state": state,
                "timestamp": "00:00:00",
            }
        }
    )["capability_registry"]["device_parameters"]
    actions = []
    for pair in evidence["pairs"]:
        device = pair["deviceId"]
        params = {k: copy.deepcopy(state[device].get(k)) for k in specs[device]}
        if not all(
            parameters._schema_field_valid(params[k], spec)
            for k, spec in specs[device].items()
        ):
            return None
        if device in ("smartWindow", "smartCurtains"):
            params["openPercentage"] = 0 if pair["action"] == "turn_off" else 100
        actions.append(
            {"deviceId": device, "action": pair["action"], "parameters": params}
        )
    return {
        "needsClarification": False,
        "message": "I will apply all requested current actions.",
        "result": actions,
    }


def _candidate_matches_inventory(initial_output, candidate_output, evidence, state):
    if outcome_family(candidate_output) != "command":
        return False, "candidate_not_ordinary_command"
    actual = action_identities(candidate_output)
    if len(actual) != len(set(actual)) or set(actual) != set(evidence["identities"]):
        return False, "action_inventory_incomplete_or_overinclusive"
    # Require a direction-consistent thermal action; no parameter score/gold.
    for _, action in parameters._actions(candidate_output):
        pair = next(p for p in evidence["pairs"] if p["deviceId"] == action["deviceId"])
        if pair.get("mode") and action["parameters"].get("mode") != pair["mode"]:
            return False, "requested_thermal_direction_not_satisfied"
        if (
            "temperature" in pair
            and action["parameters"].get("temperature") != pair["temperature"]
        ):
            return False, "explicit_temperature_not_satisfied"
    # Existing valid parameters stay fixed unless a scoped input/state target
    # establishes a change. Added actions use model generation plus schema.
    prior = {
        (a["deviceId"], a["action"]): a for _, a in parameters._actions(initial_output)
    }
    grounded = _scoped_actions(
        "",
        state,
        {"needsClarification": False, "message": "OK", "result": list(prior.values())},
        evidence,
    )
    targets = {(a["deviceId"], a["action"]): a for a in grounded["result"]}
    for _, action in parameters._actions(candidate_output):
        key = (action["deviceId"], action["action"])
        if key in targets and targets[key]["parameters"] != action["parameters"]:
            return False, "existing_action_parameters_changed_without_input_basis"
    return True, "accepted_complete_current_command"


def _prompt(request, state, timestamp, initial, evidence):
    context = base.build_model_input(
        {
            "input": {
                "userInstruction": request,
                "current_state": state,
                "timestamp": timestamp,
            }
        },
        outcome="ordinary",
    )
    return (
        "Repair one current one-time command. Return JSON only.\n"
        "Use needsClarification=false, message, result; never rule. Include EXACTLY all required device/action pairs below. "
        "No missing, duplicate or extra action is allowed. Do not copy evidence labels into action objects.\nRequired input-grounded actions:\n"
        + json.dumps(
            [
                {"deviceId": p["deviceId"], "action": p["action"]}
                for p in evidence["pairs"]
            ]
        )
        + "\nPreserve valid existing action parameters unless the user explicitly requests a change. "
        "Pure switches/shutdown inherit current settings. Thermal actions must honor heating/cooling direction. "
        "Do not invent a new temperature solely to match a hidden answer.\nContext:\n"
        + json.dumps(context, ensure_ascii=False)
        + "\nInitial:\n"
        + json.dumps(initial.get("output"), ensure_ascii=False)
    )


def repair_initial(
    request, state, timestamp, initial, candidate_generator=None, route_mode=None
):
    evidence = action_inventory(request, state)
    output = initial.get("output")
    original = copy.deepcopy(initial)
    if not evidence["eligible"]:
        # Single-device evidence can overlook an implicit second action.
        # Disable only its family recovery when completeness is unconfirmed;
        # keep its parameter/schema repairs and all real-rule behavior.
        result = parameters._repair_core(
            request, state, timestamp, original, candidate_generator, route_mode
        )
        result.update(
            protocol=PROTOCOL_ID,
            action_completeness=evidence,
            routing_recovery=None,
            schema_recovery=None,
        )
        return result
    expected = set(evidence["identities"])
    actual = action_identities(output)
    complete = (
        outcome_family(output) == "command"
        and set(actual) == expected
        and len(actual) == len(expected)
    )
    if complete:
        # Preserve parameter-repair behavior for single commands; scoped parameter checks
        # prevent multi-device numbers/settings crossing from one clause to another.
        if len(expected) == 1:
            result = parameters._repair_core(
                request, state, timestamp, original, candidate_generator, route_mode
            )
            result.update(
                protocol=PROTOCOL_ID,
                action_completeness=evidence,
                routing_recovery=None,
                schema_recovery=None,
            )
            return result
        scoped = _scoped_actions(request, state, output, evidence)
        checked = base.validate_model_output(json.dumps(scoped), state)
        changed = scoped != output
        return {
            "protocol": PROTOCOL_ID,
            "initial": original,
            "candidate": checked if changed else None,
            "final": checked if changed and checked["checker_passed"] else original,
            "triggered": changed,
            "accepted": changed and checked["checker_passed"],
            "reason": (
                "accepted_scoped_parameter_patch"
                if changed and checked["checker_passed"]
                else "repair_not_triggered"
            ),
            "operations": [],
            "structural": initial.get("checker_diagnostics") or [],
            "model_calls": 0,
            "prompt": None,
            "action_completeness": evidence,
            "routing_recovery": None,
            "schema_recovery": None,
        }
    prompt = _prompt(request, state, timestamp, original, evidence)
    result = {
        "protocol": PROTOCOL_ID,
        "initial": original,
        "candidate": None,
        "final": original,
        "triggered": True,
        "accepted": False,
        "reason": "candidate_generator_unavailable",
        "operations": [],
        "structural": initial.get("checker_diagnostics") or [],
        "model_calls": 0,
        "prompt": prompt,
        "action_completeness": evidence,
        "routing_recovery": None,
        "schema_recovery": None,
    }
    # If an existing rule already contains the complete requested action set,
    # unwrap deterministically; no model call is needed.
    pure = _pure_switch_candidate(state, evidence)
    if pure is not None:
        candidate = base.validate_model_output(json.dumps(pure), state)
    elif (
        outcome_family(output) == "rule"
        and set(actual) == expected
        and len(actual) == len(expected)
    ):
        candidate = base.validate_model_output(
            json.dumps(
                {
                    "needsClarification": False,
                    "message": "I will apply all requested current actions.",
                    "result": [
                        copy.deepcopy(a) for _, a in parameters._actions(output)
                    ],
                }
            ),
            state,
        )
    elif candidate_generator is not None:
        raw = candidate_generator(prompt)
        result["model_calls"] = 1
        candidate = base.validate_model_output(raw, state)
    else:
        return result
    result["candidate"] = candidate
    if candidate.get("output") is None:
        result["reason"] = "candidate_failed_checker"
        return result
    if outcome_family(candidate.get("output")) != "command":
        result["reason"] = "candidate_not_ordinary_command"
        return result
    # Missing parameter objects/fields may use the existing normalizer. Do not
    # hide unsupported actions, extra fields, or other errors by reserializing.
    allowed_errors = {"missing_required_parameter"}
    raw_payload = candidate.get("raw_payload")
    # An omitted parameter object produces both diagnostics. Approve the
    # action_incomplete diagnostic only when deviceId/action are present and
    # there is no unexpected raw action field. Other schema errors stay blocked.
    raw_actions = raw_payload.get("result") if isinstance(raw_payload, dict) else None
    if isinstance(raw_actions, list) and all(
        isinstance(a, dict)
        and {"deviceId", "action"}.issubset(a)
        and set(a).issubset({"deviceId", "action", "parameters"})
        for a in raw_actions
    ):
        allowed_errors.add("action_incomplete")
    closing_conflicts = []
    for diagnostic in candidate.get("checker_diagnostics") or []:
        if diagnostic.get("code") != "action_parameter_conflict":
            continue
        match = re.fullmatch(
            r"\$\.result\[(\d+)\]\.parameters\.openPercentage",
            diagnostic.get("path", ""),
        )
        raw_action = (
            raw_actions[int(match[1])]
            if match
            and isinstance(raw_actions, list)
            and int(match[1]) < len(raw_actions)
            else {}
        )
        grounded_close = (
            (raw_action.get("deviceId"), raw_action.get("action")) in expected
            and raw_action.get("deviceId") in ("smartWindow", "smartCurtains")
            and raw_action.get("action") == "turn_off"
        )
        closing_conflicts.append(bool(match and grounded_close))
    if closing_conflicts and all(closing_conflicts):
        allowed_errors.add("action_parameter_conflict")
    if set(candidate.get("checker_errors") or []) - allowed_errors:
        result["reason"] = "candidate_has_unapproved_schema_errors"
        return result
    result["raw_candidate"] = copy.deepcopy(candidate)
    # Scope parameters before acceptance; the action inventory itself is never
    # filled or filtered after generation, so partial actions cannot pass.
    scoped = _scoped_actions(request, state, candidate["output"], evidence)
    candidate = base.validate_model_output(json.dumps(scoped), state)
    result["candidate"] = candidate
    if not candidate["checker_passed"]:
        result["reason"] = "scoped_candidate_failed_checker"
        return result
    accepted, reason = _candidate_matches_inventory(
        output, candidate["output"], evidence, state
    )
    result["accepted"] = accepted
    result["reason"] = reason
    if accepted:
        result["final"] = candidate
        result["routing_recovery"] = (
            {"basis": "complete_input_grounded_current_command", "evidence": evidence}
            if outcome_family(output) == "rule"
            else None
        )
        result["schema_recovery"] = result["routing_recovery"]
    return result
