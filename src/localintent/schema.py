"""Device capabilities, normalization, validation and metric primitives."""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = ROOT / "prompts"

DEVICE_PARAMETER_KEYS = {
    "tv": ["channel", "volume"],
    "light": ["brightness"],
    "ac": ["temperature", "mode", "fanSpeed"],
    "humidifier": ["level"],
    "coffeeMachine": ["brewMode"],
    "smartCurtains": ["openPercentage"],
    "robotVacuum": ["cleaningMode"],
    "airPurifier": ["mode", "fanSpeed"],
    "smartWindow": ["openPercentage", "lockStatus"],
    "waterHeater": ["mode", "temperature"],
}

SUPPORTED_SENSORS = {
    "temperatureSensor",
    "humiditySensor",
    "indoorPollutionSensor",
    "outdoorPollutionSensor",
    "co2Sensor",
    "noiseSensor",
}

VALID_RULE_OPERATORS = {">", "<", ">=", "<=", "==", "!="}
VALID_ACTIONS = {"turn_on", "turn_off"}

DEVICE_PARAMETER_SPECS = {
    "tv": {
        "channel": {"type": "integer", "minimum": 1, "maximum": 20},
        "volume": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "light": {
        "brightness": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "ac": {
        "temperature": {"type": "integer", "minimum": 16, "maximum": 30},
        "mode": {"type": "string", "enum": ["cool", "heat"]},
        "fanSpeed": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "humidifier": {
        "level": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "coffeeMachine": {
        "brewMode": {"type": "string", "enum": ["Espresso", "Latte", "Americano"]},
    },
    "smartCurtains": {
        "openPercentage": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "robotVacuum": {
        "cleaningMode": {"type": "string", "enum": ["standard", "quiet", "turbo"]},
    },
    "airPurifier": {
        "mode": {"type": "string", "enum": ["manual", "auto"]},
        "fanSpeed": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "smartWindow": {
        "openPercentage": {"type": "integer", "minimum": 0, "maximum": 100},
        "lockStatus": {"type": "string", "enum": ["locked", "unlocked"]},
    },
    "waterHeater": {
        "mode": {"type": "string", "enum": ["heating", "keep_warm"]},
        "temperature": {"type": "integer", "minimum": 35, "maximum": 75},
    },
}

OUTPUT_SCHEMAS = {
    "non_persistent": {
        "needsClarification": "boolean",
        "message": "string",
        "result": [
            {
                "deviceId": "supported device id",
                "action": "supported action",
                "parameters": "device-specific parameter object",
            }
        ],
    },
    "rule": {
        "rule": {
            "trigger": {
                "sensor": "supported sensor id",
                "operator": "supported rule operator",
                "value": "number",
            },
            "action": {
                "deviceId": "supported device id",
                "action": "supported action",
                "parameters": "device-specific parameter object",
            },
        }
    },
}

DEVICE_DEFAULTS = {
    "tv": {"status": "off", "channel": 1, "volume": 10},
    "light": {"status": "off", "brightness": 1},
    "ac": {"status": "off", "temperature": 24, "mode": "cool", "fanSpeed": "medium"},
    "humidifier": {"status": "off", "level": 1},
    "coffeeMachine": {"status": "off", "brewMode": "Espresso"},
    "smartCurtains": {"status": "off", "openPercentage": 0},
    "robotVacuum": {"status": "off", "cleaningMode": "standard"},
    "airPurifier": {"status": "off", "mode": "manual", "fanSpeed": "low"},
    "smartWindow": {"status": "off", "openPercentage": 0, "lockStatus": "unlocked"},
    "waterHeater": {"status": "off", "mode": "keep_warm", "temperature": 45},
}

NUMERIC_PARAMETER_TOLERANCES = {
    "temperature": 1,
    "brightness": 1,
    "level": 1,
    "channel": 1,
    "volume": 5,
    "openPercentage": 5,
}


def shared_platform_context(current_state, timestamp):
    """Serialize the complete device, sensor and output-schema context."""
    return {
        "current_state": current_state,
        "timestamp": timestamp,
        "capability_registry": {
            "devices": {
                device_id: {
                    "actions": sorted(VALID_ACTIONS),
                    "parameters": DEVICE_PARAMETER_SPECS[device_id],
                }
                for device_id in sorted(DEVICE_PARAMETER_SPECS)
            },
            "sensors": sorted(SUPPORTED_SENSORS),
            "rule_operators": sorted(VALID_RULE_OPERATORS),
        },
        "output_schemas": OUTPUT_SCHEMAS,
    }


def routing_platform_context(current_state, timestamp):
    """Return only information required to classify the requested outcome."""
    return {
        "current_state": current_state,
        "timestamp": timestamp,
    }


def twostage_routing_platform_context(current_state, timestamp):
    """Return shared backend facts that are relevant to generic routing only."""
    return {
        "current_state": current_state,
        "timestamp": timestamp,
        "supported_capabilities": {
            "devices": sorted(
                device_id
                for device_id in DEVICE_PARAMETER_SPECS
                if device_id in current_state
            ),
            "sensors": sorted(
                sensor_id
                for sensor_id in SUPPORTED_SENSORS
                if sensor_id in current_state
            ),
            "actions": sorted(VALID_ACTIONS),
        },
    }


def _compact_parameter_spec(spec):
    if spec["type"] == "integer":
        return f"int[{spec['minimum']}..{spec['maximum']}]"
    return "|".join(spec["enum"])


def compact_capability_registry():
    """Serialize checker-equivalent platform constraints without repetition."""
    return {
        "actions": sorted(VALID_ACTIONS),
        "device_parameters": {
            device_id: {
                name: _compact_parameter_spec(spec) for name, spec in parameters.items()
            }
            for device_id, parameters in sorted(DEVICE_PARAMETER_SPECS.items())
        },
        "sensors": sorted(SUPPORTED_SENSORS),
        "rule_operators": sorted(VALID_RULE_OPERATORS),
        "action_parameter_constraints": {
            "smartCurtains": {
                "turn_off": {"openPercentage": "must equal 0"},
                "turn_on": {"openPercentage": "must be greater than 0"},
            },
            "smartWindow": {
                "turn_off": {"openPercentage": "must equal 0"},
                "turn_on": {"openPercentage": "must be greater than 0"},
            },
        },
    }


def compact_output_schema(outcome=None):
    """Return the relevant backend schema using a compact, explicit notation."""
    non_persistent = {
        "needsClarification": "bool",
        "message": "string",
        "result": "[{deviceId,action,parameters}]",
    }
    rule = {
        "rule": {
            "trigger": "{sensor,operator,value:number}",
            "action": "{deviceId,action,parameters}",
        }
    }
    if outcome == "rule":
        return rule
    if outcome in {
        "command",
        "clarification",
        "rejection",
        "ordinary",
        "non_persistent",
    }:
        return non_persistent
    return {
        "non_persistent": non_persistent,
        "rule": rule,
    }


def generation_platform_context(current_state, timestamp, outcome=None):
    """Return the compact shared knowledge used by generation and Repair."""
    return {
        "current_state": current_state,
        "timestamp": timestamp,
        "capability_registry": compact_capability_registry(),
        "output_schema": compact_output_schema(outcome),
    }


def load_prompt(prompt_name: str) -> str:
    """Read a packaged prompt by its method and role."""
    return (PROMPTS_DIR / f"{prompt_name}.txt").read_text(encoding="utf-8")


def extract_json_payload(text: str):
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(cleaned[index:])
            return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("No valid JSON object found in model response")


def clamp_int(value, minimum, maximum):
    if value is None:
        return None
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return None


def sanitize_parameters(device_id, parameters):
    parameters = parameters or {}

    if device_id == "tv":
        return {
            "channel": clamp_int(parameters.get("channel"), 1, 20),
            "volume": clamp_int(parameters.get("volume"), 0, 100),
        }
    if device_id == "light":
        return {"brightness": clamp_int(parameters.get("brightness"), 1, 5)}
    if device_id == "ac":
        mode = parameters.get("mode")
        if mode is not None:
            mode = str(mode).lower()
            if mode not in {"cool", "heat"}:
                mode = None
        fan_speed = parameters.get("fanSpeed")
        if fan_speed is not None:
            fan_speed = str(fan_speed).lower()
            if fan_speed not in {"low", "medium", "high"}:
                fan_speed = None
        return {
            "temperature": clamp_int(parameters.get("temperature"), 16, 30),
            "mode": mode,
            "fanSpeed": fan_speed,
        }
    if device_id == "humidifier":
        return {"level": clamp_int(parameters.get("level"), 1, 5)}
    if device_id == "coffeeMachine":
        mode = parameters.get("brewMode")
        normalized_mode = (
            None
            if mode is None
            else {
                "espresso": "Espresso",
                "latte": "Latte",
                "americano": "Americano",
            }.get(str(mode).lower())
        )
        return {"brewMode": normalized_mode}
    if device_id == "smartCurtains":
        return {"openPercentage": clamp_int(parameters.get("openPercentage"), 0, 100)}
    if device_id == "robotVacuum":
        mode = parameters.get("cleaningMode")
        normalized_mode = (
            None
            if mode is None
            else {
                "standard": "standard",
                "quiet": "quiet",
                "strong": "turbo",
                "powerful": "turbo",
                "turbo": "turbo",
            }.get(str(mode).lower())
        )
        return {"cleaningMode": normalized_mode}
    if device_id == "airPurifier":
        mode = parameters.get("mode")
        if mode is not None:
            mode = str(mode).lower()
            if mode not in {"manual", "auto"}:
                mode = None
        fan_speed = parameters.get("fanSpeed")
        if fan_speed is not None:
            fan_speed = str(fan_speed).lower()
            if fan_speed not in {"low", "medium", "high"}:
                fan_speed = None
        return {"mode": mode, "fanSpeed": fan_speed}
    if device_id == "smartWindow":
        lock_status = parameters.get("lockStatus")
        if lock_status is not None:
            lock_status = str(lock_status).lower()
            if lock_status not in {"locked", "unlocked"}:
                lock_status = None
        return {
            "openPercentage": clamp_int(parameters.get("openPercentage"), 0, 100),
            "lockStatus": lock_status,
        }
    if device_id == "waterHeater":
        mode = parameters.get("mode")
        if mode is not None:
            mode = str(mode).lower()
            if mode not in {"heating", "keep_warm"}:
                mode = None
        return {
            "mode": mode,
            "temperature": clamp_int(parameters.get("temperature"), 35, 75),
        }
    return {}


def inherit_device_parameters(device_id, parameters, current_state):
    merged = {}
    current_params = current_state.get(device_id, {})
    sanitized = sanitize_parameters(device_id, parameters)

    for key in DEVICE_PARAMETER_KEYS.get(device_id, []):
        value = sanitized.get(key)
        if value is None:
            value = current_params.get(key, DEVICE_DEFAULTS[device_id].get(key))
        merged[key] = value

    return merged


def normalize_intent_result(payload, current_state):
    if not isinstance(payload, dict):
        # Keep malformed top-level payloads invalid without throwing.
        return {
            "needsClarification": False,
            "message": "",
            "result": [],
        }

    if "rule" in payload:
        rule = payload.get("rule", {})
        action = rule.get("action", {})
        device_id = action.get("deviceId")
        if device_id in DEVICE_PARAMETER_KEYS:
            action["parameters"] = inherit_device_parameters(
                device_id, action.get("parameters"), current_state
            )
        rule["action"] = action
        return {"rule": rule}

    result_items = payload.get("result")
    if result_items is None:
        result_items = payload.get("results", [])

    normalized_result = []
    for item in result_items or []:
        if not isinstance(item, dict):
            continue
        device_id = item.get("deviceId")
        action = item.get("action")
        if device_id not in DEVICE_PARAMETER_KEYS or action not in VALID_ACTIONS:
            continue

        normalized_result.append(
            {
                "deviceId": device_id,
                "action": action,
                "parameters": inherit_device_parameters(
                    device_id, item.get("parameters"), current_state
                ),
            }
        )

    needs_clarification = bool(payload.get("needsClarification", False))
    if needs_clarification:
        normalized_result = []

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        if needs_clarification:
            message = "I need a little more information before I can decide."
        elif normalized_result:
            message = "I will handle that for you."
        else:
            message = "No action is needed right now."

    return {
        "needsClarification": needs_clarification,
        "message": message.strip(),
        "result": normalized_result,
    }


def canonicalize_result(result):
    return [
        {
            "deviceId": item["deviceId"],
            "action": item["action"],
            "parameters": {
                k: item["parameters"][k] for k in sorted(item.get("parameters", {}))
            },
        }
        for item in sorted(result, key=lambda x: (x["deviceId"], x["action"]))
    ]


def is_rule_output(output):
    return isinstance(output, dict) and isinstance(output.get("rule"), dict)


def canonicalize_rule_output(output):
    rule = output.get("rule", {})
    trigger = rule.get("trigger", {})
    action = rule.get("action", {})
    canonical_action = {
        "deviceId": action.get("deviceId"),
        "action": action.get("action"),
        "parameters": (
            {k: action["parameters"][k] for k in sorted(action.get("parameters", {}))}
            if isinstance(action.get("parameters"), dict)
            else {}
        ),
    }
    return {
        "rule": {
            "trigger": {
                "sensor": trigger.get("sensor"),
                "operator": trigger.get("operator"),
                "value": trigger.get("value"),
            },
            "action": canonical_action,
        }
    }


def canonicalize_output(output):
    if is_rule_output(output):
        return canonicalize_rule_output(output)
    return {
        "needsClarification": bool(output.get("needsClarification")),
        "message": output.get("message", ""),
        "result": canonicalize_result(output.get("result", [])),
    }


def detect_language(text):
    text = (text or "").strip()
    if not text:
        return "unknown"

    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"

    lowered = text.lower()
    french_markers = [
        " le ",
        " la ",
        " les ",
        " un ",
        " une ",
        " des ",
        " est ",
        " pour ",
        " avec ",
        "bonjour",
        "merci",
        "s'il",
        "ça",
        "être",
        "très",
        " plus ",
        " moins ",
    ]
    if any(marker in f" {lowered} " for marker in french_markers) or re.search(
        r"[àâçéèêëîïôûùüÿœ]", lowered
    ):
        return "fr"

    return "en"


def result_device_set(output):
    if is_rule_output(output):
        action = output.get("rule", {}).get("action", {})
        return [action["deviceId"]] if action.get("deviceId") else []
    return sorted({item["deviceId"] for item in output.get("result", [])})


def result_device_action_set(output):
    if is_rule_output(output):
        action = output.get("rule", {}).get("action", {})
        if action.get("deviceId") and action.get("action"):
            return [(action["deviceId"], action["action"])]
        return []
    return sorted(
        (item["deviceId"], item["action"]) for item in output.get("result", [])
    )


def parameters_match(predicted_parameters, reference_parameters):
    for key, reference_value in reference_parameters.items():
        predicted_value = predicted_parameters.get(key)
        if isinstance(reference_value, (int, float)) and isinstance(
            predicted_value, (int, float)
        ):
            tolerance = NUMERIC_PARAMETER_TOLERANCES.get(key, 0)
            if abs(predicted_value - reference_value) > tolerance:
                return False
        else:
            if predicted_value != reference_value:
                return False
    return True


def action_parameter_correct(prediction, reference):
    if is_rule_output(prediction) or is_rule_output(reference):
        if not (is_rule_output(prediction) and is_rule_output(reference)):
            return False

        prediction_rule = prediction["rule"]
        reference_rule = reference["rule"]
        prediction_trigger = prediction_rule.get("trigger", {})
        reference_trigger = reference_rule.get("trigger", {})
        if prediction_trigger != reference_trigger:
            return False

        prediction_action = prediction_rule.get("action", {})
        reference_action = reference_rule.get("action", {})
        if prediction_action.get("deviceId") != reference_action.get(
            "deviceId"
        ) or prediction_action.get("action") != reference_action.get("action"):
            return False

        return parameters_match(
            prediction_action.get("parameters", {}),
            reference_action.get("parameters", {}),
        )

    prediction_items = {
        (item["deviceId"], item["action"]): item["parameters"]
        for item in prediction.get("result", [])
    }
    reference_items = {
        (item["deviceId"], item["action"]): item["parameters"]
        for item in reference.get("result", [])
    }

    if prediction_items.keys() != reference_items.keys():
        return False

    return all(
        parameters_match(prediction_items[key], reference_items[key])
        for key in reference_items
    )


def output_mode_correct(prediction, reference):
    return is_rule_output(prediction) == is_rule_output(reference)


def rule_intent_understanding_correct(prediction, reference):
    if not (is_rule_output(prediction) and is_rule_output(reference)):
        return False

    prediction_rule = prediction["rule"]
    reference_rule = reference["rule"]
    prediction_trigger = prediction_rule.get("trigger", {})
    reference_trigger = reference_rule.get("trigger", {})
    prediction_action = prediction_rule.get("action", {})
    reference_action = reference_rule.get("action", {})

    return (
        prediction_trigger.get("sensor") == reference_trigger.get("sensor")
        and prediction_action.get("deviceId") == reference_action.get("deviceId")
        and prediction_action.get("action") == reference_action.get("action")
    )


def output_format_valid(output):
    if is_rule_output(output):
        rule = output.get("rule", {})
        trigger = rule.get("trigger", {})
        action = rule.get("action", {})
        device_id = action.get("deviceId")

        if set(output.keys()) != {"rule"}:
            return False
        if set(rule.keys()) != {"trigger", "action"}:
            return False
        if set(trigger.keys()) != {"sensor", "operator", "value"}:
            return False
        if trigger.get("sensor") not in SUPPORTED_SENSORS:
            return False
        if trigger.get("operator") not in VALID_RULE_OPERATORS:
            return False
        if not isinstance(trigger.get("value"), (int, float)):
            return False
        if device_id not in DEVICE_PARAMETER_KEYS:
            return False
        if action.get("action") not in VALID_ACTIONS:
            return False
        if not isinstance(action.get("parameters"), dict):
            return False
        if "status" in action.get("parameters", {}):
            return False
        return sorted(action["parameters"].keys()) == sorted(
            DEVICE_PARAMETER_KEYS[device_id]
        )

    result = output.get("result", [])
    if set(output.keys()) != {"needsClarification", "message", "result"}:
        return False
    if not isinstance(output.get("needsClarification"), bool):
        return False
    if not isinstance(output.get("message"), str) or not output["message"].strip():
        return False
    if not isinstance(result, list):
        return False
    if output["needsClarification"] and result:
        return False

    for item in result:
        if set(item.keys()) != {"deviceId", "action", "parameters"}:
            return False
        device_id = item.get("deviceId")
        if device_id not in DEVICE_PARAMETER_KEYS:
            return False
        if item.get("action") not in VALID_ACTIONS:
            return False
        if not isinstance(item.get("parameters"), dict):
            return False
        if "status" in item["parameters"]:
            return False
        if sorted(item["parameters"].keys()) != sorted(
            DEVICE_PARAMETER_KEYS[device_id]
        ):
            return False

    return True


def make_diagnostic(code, path, message, received=None, allowed=None):
    diagnostic = {"code": code, "path": path, "message": message}
    if received is not None:
        diagnostic["received"] = received
    if allowed is not None:
        diagnostic["allowed"] = allowed
    return diagnostic


def _is_json_integer(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and float(value).is_integer()
    )


def _raw_action_items(payload):
    """Return raw action locations without normalizing or dropping invalid data."""
    if not isinstance(payload, dict):
        return []
    if "rule" in payload:
        rule = payload.get("rule")
        if not isinstance(rule, dict) or "action" not in rule:
            return []
        return [("$.rule.action", rule.get("action"), True)]
    result = payload.get("result", payload.get("results"))
    if not isinstance(result, list):
        return []
    return [(f"$.result[{index}]", item, False) for index, item in enumerate(result)]


def raw_parameter_completeness_details(payload):
    """Audit whether model-authored actions contain every backend parameter key."""
    action_items = _raw_action_items(payload)
    if not action_items:
        return {
            "applicable": False,
            "complete": None,
            "missing": [],
        }

    missing = []
    for path, item, _ in action_items:
        if not isinstance(item, dict):
            missing.append(
                {
                    "path": path,
                    "missing_keys": ["deviceId", "action", "parameters"],
                }
            )
            continue
        device_id = item.get("deviceId")
        expected_keys = DEVICE_PARAMETER_KEYS.get(device_id)
        parameters = item.get("parameters")
        if expected_keys is None:
            missing.append(
                {
                    "path": f"{path}.parameters",
                    "missing_keys": ["unknown_for_unsupported_device"],
                }
            )
            continue
        if not isinstance(parameters, dict):
            missing.append(
                {
                    "path": f"{path}.parameters",
                    "missing_keys": list(expected_keys),
                }
            )
            continue
        missing_keys = sorted(set(expected_keys) - set(parameters))
        if missing_keys:
            missing.append(
                {
                    "path": f"{path}.parameters",
                    "missing_keys": missing_keys,
                }
            )

    return {
        "applicable": True,
        "complete": not missing,
        "missing": missing,
    }


def normalization_change_details(before, after, path="$"):
    """Describe deterministic parser/normalizer edits without using a reference."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}"
            if key not in before:
                changes.append(
                    {
                        "path": child_path,
                        "change": "inserted",
                        "before": None,
                        "after": after[key],
                    }
                )
            elif key not in after:
                changes.append(
                    {
                        "path": child_path,
                        "change": "removed",
                        "before": before[key],
                        "after": None,
                    }
                )
            else:
                changes.extend(
                    normalization_change_details(before[key], after[key], child_path)
                )
        return changes

    if isinstance(before, list) and isinstance(after, list):
        changes = []
        common_length = min(len(before), len(after))
        for index in range(common_length):
            changes.extend(
                normalization_change_details(
                    before[index],
                    after[index],
                    f"{path}[{index}]",
                )
            )
        for index in range(common_length, len(before)):
            changes.append(
                {
                    "path": f"{path}[{index}]",
                    "change": "removed",
                    "before": before[index],
                    "after": None,
                }
            )
        for index in range(common_length, len(after)):
            changes.append(
                {
                    "path": f"{path}[{index}]",
                    "change": "inserted",
                    "before": None,
                    "after": after[index],
                }
            )
        return changes

    if before != after or type(before) is not type(after):
        return [
            {
                "path": path,
                "change": "replaced",
                "before": before,
                "after": after,
            }
        ]
    return []


def _parameter_diagnostics(item, path, device_id, is_rule_action):
    diagnostics = []
    if "parameters" not in item:
        expected = DEVICE_PARAMETER_KEYS.get(device_id, [])
        diagnostics.append(
            make_diagnostic(
                "missing_required_parameter",
                f"{path}.parameters",
                f"Add the required parameter object for device {device_id!r} with fields {expected!r}.",
                allowed=expected,
            )
        )
        return diagnostics

    parameters = item.get("parameters")
    if not isinstance(parameters, dict):
        diagnostics.append(
            make_diagnostic(
                "parameters_not_object",
                f"{path}.parameters",
                f"Parameters for device {device_id!r} must be one object.",
                received=type(parameters).__name__,
                allowed="object",
            )
        )
        return diagnostics

    expected_keys = set(DEVICE_PARAMETER_KEYS[device_id])
    missing_keys = sorted(expected_keys - set(parameters))
    if missing_keys:
        diagnostics.append(
            make_diagnostic(
                "missing_required_parameter",
                f"{path}.parameters",
                f"Add missing parameter fields {missing_keys!r} for device {device_id!r}.",
                received=sorted(parameters),
                allowed=sorted(expected_keys),
            )
        )

    unsupported_keys = sorted(set(parameters) - expected_keys)
    if unsupported_keys:
        diagnostics.append(
            make_diagnostic(
                "unsupported_parameter_field",
                f"{path}.parameters",
                f"Remove unsupported parameter fields {unsupported_keys!r} for device {device_id!r}. Allowed fields: {sorted(expected_keys)!r}.",
                received=unsupported_keys,
                allowed=sorted(expected_keys),
            )
        )

    for key in sorted(expected_keys & set(parameters)):
        raw_value = parameters[key]
        spec = DEVICE_PARAMETER_SPECS[device_id][key]
        value_path = f"{path}.parameters.{key}"
        if spec["type"] == "integer":
            if not _is_json_integer(raw_value):
                diagnostics.append(
                    make_diagnostic(
                        "invalid_parameter_type",
                        value_path,
                        f"Parameter {key!r} for device {device_id!r} must be an integer.",
                        received=raw_value,
                        allowed=f"integer in [{spec['minimum']}, {spec['maximum']}]",
                    )
                )
            elif not spec["minimum"] <= raw_value <= spec["maximum"]:
                diagnostics.append(
                    make_diagnostic(
                        "invalid_parameter_value",
                        value_path,
                        f"Parameter {key!r} value {raw_value!r} is outside the allowed range for device {device_id!r}.",
                        received=raw_value,
                        allowed=spec,
                    )
                )
        elif not isinstance(raw_value, str):
            diagnostics.append(
                make_diagnostic(
                    "invalid_parameter_type",
                    value_path,
                    f"Parameter {key!r} for device {device_id!r} must be a string.",
                    received=raw_value,
                    allowed=spec["enum"],
                )
            )
        elif raw_value not in spec["enum"]:
            diagnostics.append(
                make_diagnostic(
                    "invalid_parameter_value",
                    value_path,
                    f"Parameter {key!r} has invalid value {raw_value!r} for device {device_id!r}.",
                    received=raw_value,
                    allowed=spec["enum"],
                )
            )

    if (
        device_id in {"smartCurtains", "smartWindow"}
        and "openPercentage" in parameters
        and _is_json_integer(parameters["openPercentage"])
    ):
        action = item.get("action")
        open_percentage = parameters["openPercentage"]
        conflict = (action == "turn_off" and open_percentage != 0) or (
            action == "turn_on" and open_percentage <= 0
        )
        if conflict:
            code = (
                "rule_internal_conflict"
                if is_rule_action
                else "action_parameter_conflict"
            )
            expected = (
                "openPercentage must be 0 for turn_off"
                if action == "turn_off"
                else "openPercentage must be greater than 0 for turn_on"
            )
            diagnostics.append(
                make_diagnostic(
                    code,
                    f"{path}.parameters.openPercentage",
                    f"Action {action!r} conflicts with openPercentage={open_percentage!r}; {expected}.",
                    received=open_percentage,
                    allowed=expected,
                )
            )

    return diagnostics


def normalization_diagnostic_details(payload, current_state):
    """Validate raw backend readiness and report deterministic repair guidance."""
    if not isinstance(payload, dict):
        return [
            make_diagnostic(
                "parsed_payload_not_object",
                "$",
                "The parsed output must be one JSON object.",
                received=type(payload).__name__,
                allowed="object",
            )
        ]

    if "rule" in payload:
        rule = payload.get("rule")
        if not isinstance(rule, dict):
            return [
                make_diagnostic(
                    "rule_not_object",
                    "$.rule",
                    "The rule field must be one object.",
                    received=type(rule).__name__,
                    allowed="object",
                )
            ]

        diagnostics = []
        if set(payload) != {"rule"}:
            if "action" in payload and "action" not in rule:
                diagnostics.append(
                    make_diagnostic(
                        "rule_action_must_be_nested_under_rule",
                        "$.action",
                        "Move the top-level action to $.rule.action; $.rule.action must be one object, not an array.",
                        received=type(payload.get("action")).__name__,
                        allowed="object at $.rule.action",
                    )
                )
            else:
                extra_fields = sorted(set(payload) - {"rule"})
                diagnostics.append(
                    make_diagnostic(
                        "unexpected_rule_top_level_fields",
                        "$",
                        f"Remove unexpected top-level rule fields: {', '.join(extra_fields)}.",
                        received=extra_fields,
                        allowed=["rule"],
                    )
                )
        if "trigger" not in rule:
            diagnostics.append(
                make_diagnostic(
                    "rule_trigger_incomplete",
                    "$.rule.trigger",
                    "Add the required $.rule.trigger object.",
                    allowed="object with sensor, operator, and value",
                )
            )
        else:
            trigger = rule.get("trigger")
            if not isinstance(trigger, dict):
                diagnostics.append(
                    make_diagnostic(
                        "rule_trigger_incomplete",
                        "$.rule.trigger",
                        "The Rule trigger must be one object with sensor, operator, and value.",
                        received=type(trigger).__name__,
                        allowed=["sensor", "operator", "value"],
                    )
                )
            else:
                missing_trigger_fields = sorted(
                    {"sensor", "operator", "value"} - set(trigger)
                )
                extra_trigger_fields = sorted(
                    set(trigger) - {"sensor", "operator", "value"}
                )
                if missing_trigger_fields or extra_trigger_fields:
                    diagnostics.append(
                        make_diagnostic(
                            "rule_trigger_incomplete",
                            "$.rule.trigger",
                            f"Use exactly sensor, operator, and value; missing={missing_trigger_fields!r}, unexpected={extra_trigger_fields!r}.",
                            received=sorted(trigger),
                            allowed=["sensor", "operator", "value"],
                        )
                    )
                sensor = trigger.get("sensor")
                if sensor not in SUPPORTED_SENSORS or sensor not in current_state:
                    diagnostics.append(
                        make_diagnostic(
                            "unsupported_or_ungrounded_sensor",
                            "$.rule.trigger.sensor",
                            f"Sensor {sensor!r} is unsupported or absent from current context.",
                            received=sensor,
                            allowed=sorted(
                                item
                                for item in SUPPORTED_SENSORS
                                if item in current_state
                            ),
                        )
                    )
                operator = trigger.get("operator")
                if operator not in VALID_RULE_OPERATORS:
                    diagnostics.append(
                        make_diagnostic(
                            "unsupported_rule_operator",
                            "$.rule.trigger.operator",
                            f"Rule operator {operator!r} is unsupported.",
                            received=operator,
                            allowed=sorted(VALID_RULE_OPERATORS),
                        )
                    )
                value = trigger.get("value")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    diagnostics.append(
                        make_diagnostic(
                            "invalid_trigger_value",
                            "$.rule.trigger.value",
                            "Rule trigger value must be one finite number.",
                            received=value,
                            allowed="finite number",
                        )
                    )
        if "action" not in rule:
            diagnostics.append(
                make_diagnostic(
                    "rule_action_incomplete",
                    "$.rule.action",
                    "Add the required $.rule.action as one action object, not an array.",
                    allowed="object with deviceId, action, and parameters",
                )
            )
            action_items = []
        else:
            action_items = [("$.rule.action", rule.get("action"))]
    else:
        diagnostics = []
        expected_top_level = {"needsClarification", "message", "result"}
        missing_top_level = sorted(expected_top_level - set(payload))
        unexpected_top_level = sorted(set(payload) - expected_top_level)
        if missing_top_level or unexpected_top_level:
            diagnostics.append(
                make_diagnostic(
                    "outcome_schema_conflict",
                    "$",
                    f"Use exactly needsClarification, message, and result; missing={missing_top_level!r}, unexpected={unexpected_top_level!r}.",
                    received=sorted(payload),
                    allowed=sorted(expected_top_level),
                )
            )
        if not isinstance(payload.get("needsClarification"), bool):
            diagnostics.append(
                make_diagnostic(
                    "outcome_schema_conflict",
                    "$.needsClarification",
                    "needsClarification must be a boolean.",
                    received=payload.get("needsClarification"),
                    allowed="boolean",
                )
            )
        if (
            not isinstance(payload.get("message"), str)
            or not payload.get("message", "").strip()
        ):
            diagnostics.append(
                make_diagnostic(
                    "outcome_schema_conflict",
                    "$.message",
                    "message must be one non-empty string.",
                    received=payload.get("message"),
                    allowed="non-empty string",
                )
            )
        result_items = payload.get("result", payload.get("results", []))
        if not isinstance(result_items, list):
            diagnostics.append(
                make_diagnostic(
                    "result_not_array",
                    "$.result",
                    "The result field must be an array.",
                    received=type(result_items).__name__,
                    allowed="array",
                )
            )
            action_items = []
        else:
            if payload.get("needsClarification") is True and result_items:
                diagnostics.append(
                    make_diagnostic(
                        "outcome_schema_conflict",
                        "$.result",
                        "Clarification output must not contain executable actions.",
                        received=f"{len(result_items)} action(s)",
                        allowed=[],
                    )
                )
            action_items = [
                (f"$.result[{index}]", item) for index, item in enumerate(result_items)
            ]

    for path, item in action_items:
        if not isinstance(item, dict):
            diagnostics.append(
                make_diagnostic(
                    "action_not_object",
                    path,
                    f"{path} must be one action object.",
                    received=type(item).__name__,
                    allowed="object",
                )
            )
            continue

        required_action_fields = {"deviceId", "action", "parameters"}
        missing_action_fields = sorted(required_action_fields - set(item))
        unexpected_action_fields = sorted(set(item) - required_action_fields)
        if missing_action_fields or unexpected_action_fields:
            code = (
                "rule_action_incomplete"
                if path == "$.rule.action"
                else "action_incomplete"
            )
            diagnostics.append(
                make_diagnostic(
                    code,
                    path,
                    f"Use exactly deviceId, action, and parameters; missing={missing_action_fields!r}, unexpected={unexpected_action_fields!r}.",
                    received=sorted(item),
                    allowed=sorted(required_action_fields),
                )
            )

        device_id = item.get("deviceId")
        action = item.get("action")
        if device_id not in DEVICE_PARAMETER_KEYS or device_id not in current_state:
            diagnostics.append(
                make_diagnostic(
                    "unsupported_or_ungrounded_device",
                    f"{path}.deviceId",
                    f"Device {device_id!r} is unsupported or absent from current context. Use one grounded device id.",
                    received=device_id,
                    allowed=sorted(
                        device
                        for device in DEVICE_PARAMETER_KEYS
                        if device in current_state
                    ),
                )
            )
            continue
        if "action" in item and action not in VALID_ACTIONS:
            diagnostics.append(
                make_diagnostic(
                    "unsupported_action",
                    f"{path}.action",
                    f"Action {action!r} is unsupported for device {device_id!r}. Use turn_on or turn_off.",
                    received=action,
                    allowed=sorted(VALID_ACTIONS),
                )
            )

        diagnostics.extend(
            _parameter_diagnostics(
                item,
                path,
                device_id,
                is_rule_action=path == "$.rule.action",
            )
        )

    unique = {}
    for diagnostic in diagnostics:
        identity = (diagnostic["code"], diagnostic["path"], diagnostic["message"])
        unique[identity] = diagnostic
    return [unique[key] for key in sorted(unique)]


def normalization_diagnostics(payload, current_state):
    """Keep stable checker codes for compatibility and error taxonomy."""
    return sorted(
        {
            diagnostic["code"]
            for diagnostic in normalization_diagnostic_details(payload, current_state)
        }
    )


def language_consistency_correct(prediction, instruction_language):
    if instruction_language == "unknown":
        return False

    if is_rule_output(prediction):
        rule = prediction.get("rule", {})
        return set(prediction.keys()) == {"rule"} and set(rule.keys()) == {
            "trigger",
            "action",
        }

    message_language = detect_language(prediction.get("message", ""))
    return message_language == instruction_language
