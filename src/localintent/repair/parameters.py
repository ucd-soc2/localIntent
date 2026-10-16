"""Input-grounded parameter operations and minimal-change acceptance."""

import copy
import json
import math
import re
from .. import core as base
from .common import action_identities, outcome_family

PROTOCOL_ID = "grounded"


def _actions(output):
    if not isinstance(output, dict):
        return []
    if isinstance(output.get("rule"), dict) and isinstance(
        output["rule"].get("action"), dict
    ):
        return [(("rule", "action"), output["rule"]["action"])]
    return [
        (("result", i), a)
        for i, a in enumerate(output.get("result", []))
        if isinstance(a, dict)
    ]


def _get(obj, path):
    for k in path:
        obj = obj[k]
    return obj


def _set(obj, path, value):
    parent = _get(obj, path[:-1])
    parent[path[-1]] = value


def _differences(a, b, path=()):
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        return {path}
    if isinstance(a, dict):
        diffs = set()
        for k in set(a) | set(b):
            diffs |= (
                {path + (k,)}
                if k not in a or k not in b
                else _differences(a[k], b[k], path + (k,))
            )
        return diffs
    if isinstance(a, list):
        if len(a) != len(b):
            return {path}
        return (
            set().union(
                *(_differences(x, y, path + (i,)) for i, (x, y) in enumerate(zip(a, b)))
            )
            if a
            else set()
        )
    return {path} if a != b else set()


def _conditional_text(text):
    matches = list(re.finditer(r"\b(?:whenever|when|if)\b", text))
    clause = text[matches[-1].end() :] if matches else text
    # Separate the condition from a following action. In “if this hot again,
    # cool to 23 degrees”, 23 is an actuator target, not a sensor threshold.
    return re.split(r"[,;!?]|\.(?!\d)|\bthen\b", clause, maxsplit=1)[0]


def _sensor_candidates(text):
    found = set()
    if re.search(r"\b(?:noise|noisy|loud|racket|din|commotion)\b", text):
        found.add("noiseSensor")
    if re.search(
        r"\b(?:cold|colder|chilly|chill|icy|hot|heat|heats|warmth|warms|warm|temperature|sweltering|overheated)\b",
        text,
    ):
        found.add("temperatureSensor")
    if re.search(
        r"\b(?:humidity|humid|damp|dry|dryness|parched|moisture)\b", text
    ) and not re.search(r"\b(?:dust|grit|crumbs)\b", text):
        found.add("humiditySensor")
    if re.search(r"\b(?:co2|carbon dioxide)\b", text):
        found.add("co2Sensor")
    pollution = bool(
        re.search(
            r"\b(?:pollut\w*|smok\w*|foul\w*|dirty|dust\w*|unclean|haze|clean)\b", text
        )
    )
    outside = bool(
        re.search(r"\b(?:outside|outdoors?|street|beyond the window)\b", text)
    )
    inside = bool(
        re.search(
            r"\b(?:inside|indoors?|airborne)\b|\broom air\b|\bair[^.!?]{0,20}in (?:the |this )?room\b|\bair around my chair\b",
            text,
        )
    )
    if pollution and outside:
        found.add("outdoorPollutionSensor")
    if pollution and inside:
        found.add("indoorPollutionSensor")
    return found


def _operator(text, sensor):
    if re.search(r"\b(?:at least|no less than)\b|>=", text):
        return ">="
    if re.search(r"\b(?:at most|no more than)\b|<=", text):
        return "<="
    if re.search(r"\b(?:below|under|less than)\b", text):
        return "<"
    if re.search(r"\b(?:above|over|greater than)\b", text):
        return ">"
    if sensor == "temperatureSensor":
        cold = bool(
            re.search(r"\b(?:cold|colder|chilly|chill|icy|falls?|drops?)\b", text)
        )
        hot = bool(
            re.search(
                r"\b(?:hot|heat|heats|warmth|warm|warms|sweltering|overheated|rises?)\b",
                text,
            )
        )
        return "<=" if cold and not hot else ">=" if hot and not cold else None
    if sensor == "humiditySensor":
        dry = bool(re.search(r"\b(?:dry|dryness|parched)\b", text))
        damp = bool(re.search(r"\b(?:humid|damp)\b", text))
        return "<=" if dry and not damp else ">=" if damp and not dry else None
    if sensor in ("outdoorPollutionSensor", "indoorPollutionSensor"):
        return (
            "<="
            if re.search(r"\bclean\b", text)
            and not re.search(
                r"\b(?:dirty|unclean|dust\w*|smok\w*|pollut\w*|foul\w*)\b", text
            )
            else ">="
        )
    if sensor in ("noiseSensor", "co2Sensor"):
        return ">="
    return None


def _reach_direction(clause, text, sensor):
    """Ground neutral 'reaches' from explicit comparison or thermal response.

    It is not a blanket >= rule. A cooling response supports an upper boundary,
    a heating response supports a lower one; an unrelated action is ambiguous.
    The action target never supplies the condition's numeric threshold.
    """
    if re.search(r"\bnot equal\b|!=", clause):
        return "!="
    if re.search(r"\bexactly\b|\bequals?\b|==", clause):
        return "=="
    cold = bool(
        re.search(r"\b(?:falls?|drops?|decreases?|cold|colder|chilly|icy)\b", clause)
    )
    hot = bool(
        re.search(
            r"\b(?:rises?|climbs?|increases?|hot|heat|warms?|sweltering)\b", clause
        )
    )
    if cold and hot:
        return None
    direction = _operator(clause, sensor)
    if direction:
        return direction
    matches = list(re.finditer(r"\b(?:whenever|when|if)\b", text))
    condition = text[matches[-1].end() :] if matches else text
    parts = re.split(r"[,;!?]|\.(?!\d)|\bthen\b", condition, maxsplit=1)
    action = parts[1] if len(parts) > 1 else ""
    if sensor != "temperatureSensor" or re.search(
        r"\b(?:do not|don.t|never|avoid|stop)\b", action
    ):
        return None
    cooling = bool(re.search(r"\bcool(?:ing)?\b", action))
    heating = bool(re.search(r"\b(?:heat|heating|warm|warming)\b", action))
    if cooling and not heating:
        return ">="
    if heating and not cooling:
        return "<="
    return None


def trigger_target(request, state):
    """Return a target only for a unique sensor and an explicit/state anchor."""
    text = request.lower()
    if not re.search(
        r"\b(?:whenever|when|if|in future|from now on|each time|every time|automatically)\b",
        text,
    ):
        return None
    clause = _conditional_text(text)
    sensors = _sensor_candidates(clause)
    if not sensors:
        sensors = _sensor_candidates(text)
    if len(sensors) != 1:
        return None
    sensor = next(iter(sensors))
    direction = (
        _reach_direction(clause, text, sensor)
        if re.search(r"\breaches?\s+(?:exactly\s+)?-?\d", clause)
        else (_operator(clause, sensor) or _operator(text, sensor))
    )
    if not direction:
        return None
    if re.search(r"\bbetween\b|\brange\b", clause):
        return None  # A compound interval is not collapsed to a one-sided rule.
    numbered = re.findall(
        r"(?:at least|at most|no less than|no more than|below|above|under|over|less than|greater than|falls? to|drops? to|rises? to|reaches?|>=|<=)\s*(-?\d+(?:\.\d+)?)",
        clause,
    )
    if not numbered:
        units = {
            "noiseSensor": r"db|decibels?",
            "temperatureSensor": r"°c|degrees?(?:\s+celsius)?|celsius",
            "humiditySensor": r"%|percent",
            "co2Sensor": r"ppm",
            "indoorPollutionSensor": r"aqi",
            "outdoorPollutionSensor": r"aqi",
        }[sensor]
        numbered = re.findall(r"(-?\d+(?:\.\d+)?)\s*(?:" + units + r")(?!\w)", clause)
    if len(set(numbered)) == 1:
        value = float(numbered[0])
        return (
            {
                "sensor": sensor,
                "operator": direction,
                "value": value,
                "basis": "explicit_threshold",
            }
            if math.isfinite(value)
            else None
        )
    if numbered:
        return None
    anchored = bool(
        re.search(
            r"\bthis (?:loud|noisy|cold|chilly|hot|warm|dry|parched|damp|humid|dirty|polluted|unclean|dusty|bad|point|level|much|warmth|kind of chill)\b|\blike this\b|\blike it is now\b|\bas (?:[^.!?]{0,45}) as (?:today|now|it does now)\b|\breaches this point\b",
            clause,
        )
    )
    value = state.get(sensor)
    if (
        anchored
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return {
            "sensor": sensor,
            "operator": direction,
            "value": value,
            "basis": "explicit_current_state_anchor",
        }
    return None


def _number_target(text, device, field):
    if field == "openPercentage":
        m = re.search(
            r"\b(?:open|opening|window|curtains?)\b[^.!?]{0,65}?\b(\d+(?:\.\d+)?)\s*(?:%|percent)",
            text,
        )
        if m:
            return float(m.group(1))
        if re.search(r"\b(?:open|window|curtains?)\b[^.!?]{0,45}\bhalfway\b", text):
            return 50
    if field == "temperature":
        m = re.search(
            r"\b(?:set|adjust|raise|lower|target|heat the water|heat water|warm the water|cool (?:the |this )?(?:room|it)|heat (?:the |this )?room)\b[^.!?]{0,65}?\b(?:to|at)\s*(\d+(?:\.\d+)?)\s*(?:°c|degrees?|celsius)\b",
            text,
        )
        if m:
            return float(m.group(1))
    if field in ("volume", "channel", "brightness"):
        m = re.search(r"\b" + field + r"\s*(?:to|at|of|=)?\s*(\d+)\b", text)
        if m:
            return int(m.group(1))
    return None


def _state_repair_plan(request, state, output):
    text = request.lower()
    operations = []

    def add(path, value, basis):
        try:
            old = _get(output, path)
        except (KeyError, IndexError, TypeError):
            return
        if old != value:
            operations.append(
                {"path": list(path), "old": old, "target": value, "basis": basis}
            )

    if isinstance(output, dict) and isinstance(output.get("rule"), dict):
        target = trigger_target(request, state)
        trigger = output["rule"].get("trigger")
        if target and isinstance(trigger, dict):
            for k in ("sensor", "operator", "value"):
                add(("rule", "trigger", k), target[k], target["basis"])
    for path, action in _actions(output):
        device = action.get("deviceId")
        verb = action.get("action")
        params = action.get("parameters")
        if not isinstance(params, dict):
            continue
        explicit = set()
        for field in params:
            value = _number_target(text, device, field)
            if value is not None:
                add(path + ("parameters", field), value, "explicit_user_parameter")
                explicit.add(field)
        if device in ("smartWindow", "smartCurtains") and "openPercentage" in params:
            if verb == "turn_off" and "openPercentage" not in explicit:
                add(path + ("parameters", "openPercentage"), 0, "closing_postcondition")
            elif (
                verb == "turn_on"
                and "openPercentage" not in explicit
                and re.search(r"\bopen\b", text)
                and not re.search(
                    r"\b(?:partly|partially|slightly|a little|halfway)\b", text
                )
            ):
                add(
                    path + ("parameters", "openPercentage"),
                    100,
                    "unqualified_open_postcondition",
                )
        if verb != "turn_on":
            continue  # Closing does not reset unrelated settings.
        if device == "coffeeMachine" and re.search(r"\bespresso\b", text):
            add(
                path + ("parameters", "brewMode"),
                "Espresso",
                "explicit_beverage_choice",
            )
        if device == "ac":
            cold = bool(
                re.search(
                    r"\b(?:cold|colder|chilly|chilled|shivering|icy|warmer)\b|\b(?:want|need|like|more)\b[^.!?]{0,30}\bwarmth\b",
                    text,
                )
            )
            hot = bool(
                re.search(
                    r"\b(?:hot|sweltering|overheated|oppressive)\b|\b(?:get|start|need|want)\b[^.!?]{0,25}\bcooling\b",
                    text,
                )
            )
            if cold and not hot:
                add(
                    path + ("parameters", "mode"), "heat", "requested_heating_direction"
                )
            # No arbitrary >=26 target inferred from cold alone.
        if (
            device == "light"
            and "brightness" in params
            and "brightness" not in explicit
        ):
            poor = bool(
                re.search(
                    r"\b(?:barely see|cannot see|can.t see|too dark|hard to see|straining[^.!?]{0,30}see)\b",
                    text,
                )
            )
            fine = bool(
                re.search(
                    r"\b(?:book|read|reading|small print|letter|tiny bead|thread\w*|needle|fine stitches|stitching|sewing|detailed work|fine work)\b",
                    text,
                )
            )
            low_light = bool(
                re.search(
                    r"\b(?:dark|dim|no daylight|more light|not enough light)\b", text
                )
            )
            squint = bool(re.search(r"\bsquint(?:ing)?\b", text)) and not re.search(
                r"\b(?:not|never|without|no longer)\b[^.!?]{0,20}\bsquint(?:ing)?\b",
                text,
            )
            conflict = bool(
                re.search(r"\b(?:glare|glaring|dazzl\w*|too bright|less light)\b", text)
            )
            poor = poor or (squint and low_light and not conflict)
            if conflict:
                poor = False
            danger = bool(re.search(r"\b(?:trip|stumble|rug edge)\b", text))
            minimum = 5 if poor and (fine or danger) else 4 if poor else None
            if (
                minimum is not None
                and isinstance(params["brightness"], (int, float))
                and params["brightness"] < minimum
            ):
                add(
                    path + ("parameters", "brightness"),
                    minimum,
                    (
                        "fine_or_safety_visibility"
                        if minimum == 5
                        else "low_visibility_minimum"
                    ),
                )
        if device == "robotVacuum" and "cleaningMode" in params:
            severe = bool(
                re.search(
                    r"\b(?:thick|heavy|heavily)\b[^.!?]{0,40}\b(?:dust|grit|dirt)\b|\b(?:quite|very|really) dirty\b|\bthorough(?:ly)?\b|\bremains after (?:an? )?(?:ordinary|normal) clean",
                    text,
                )
            )
            if severe:
                add(
                    path + ("parameters", "cleaningMode"),
                    "turbo",
                    "severe_cleaning_convention",
                )
        if device == "airPurifier":
            respiratory = bool(re.search(r"\b(?:sneez\w*|cough\w*)\b", text))
            severe = respiratory or bool(
                re.search(
                    r"\bair\b[^.!?]{0,70}\b(?:heavy|uncomfortable|bad|dead)\b|\bsmells dusty\b",
                    text,
                )
            )
            if severe:
                add(
                    path + ("parameters", "fanSpeed"),
                    "high",
                    "strong_air_discomfort_convention",
                )
            if respiratory or re.search(
                r"\bsmells dusty\b|\bair\b[^.!?]{0,30}\bdead\b", text
            ):
                add(
                    path + ("parameters", "mode"),
                    "manual",
                    "respiratory_or_stale_air_convention",
                )
        if device == "waterHeater":
            if re.search(
                r"\bwater\b[^.!?]{0,50}\b(?:still cool|cold|not warm|too cool)\b", text
            ):
                add(
                    path + ("parameters", "mode"),
                    "heating",
                    "observed_unmet_water_heating_need",
                )
            if re.search(
                r"\bwater\b[^.!?]{0,50}\b(?:already warm|warm enough|satisfactor\w*)\b",
                text,
            ) and re.search(r"\b(?:keep|maintain|hold)\b", text):
                add(
                    path + ("parameters", "mode"),
                    "keep_warm",
                    "satisfied_water_warmth_maintenance",
                )
            if "temperature" not in explicit and re.search(
                r"\bkeep\b[^.!?]{0,50}\b(?:setting|target)\b", text
            ):
                value = state.get(device, {}).get("temperature")
                if value is not None:
                    add(
                        path + ("parameters", "temperature"),
                        value,
                        "explicit_existing_setting_preference",
                    )
            # Shower/bath alone does not establish readiness or a 60C target.
    return operations


DEVICE_ALIASES = {
    "ac": r"\b(?:ac|air[ -]conditioner)\b",
    "waterHeater": r"\bwater heater\b",
    "robotVacuum": r"\b(?:robot vacuum|vacuum)\b",
    "tv": r"\b(?:tv|television)\b",
    "airPurifier": r"\b(?:air purifier|purifier)\b",
    "light": r"\b(?:light|lamp)\b",
    "humidifier": r"\bhumidifier\b",
    "coffeeMachine": r"\bcoffee machine\b",
    "smartWindow": r"\bwindow\b",
    "smartCurtains": r"\bcurtains?\b",
}

RETAINABLE_FIELDS = {
    "ac": {
        "temperature": r"\b(?:temperature|target)\b",
        "mode": r"\bmode\b",
        "fanSpeed": r"\bfan[ -]speed\b",
    },
    "waterHeater": {"temperature": r"\b(?:temperature|target)\b", "mode": r"\bmode\b"},
    "robotVacuum": {"cleaningMode": r"\bcleaning[ -]mode\b"},
    "tv": {"channel": r"\bchannel\b", "volume": r"\bvolume\b"},
    "airPurifier": {"mode": r"\bmode\b", "fanSpeed": r"\bfan[ -]speed\b"},
    "light": {"brightness": r"\bbrightness\b"},
    "humidifier": {"level": r"\blevel\b"},
    "coffeeMachine": {"brewMode": r"\bbrew[ -]mode\b"},
}


def _action_context(request):
    """Separate action directives from a sensor condition and its numbers."""
    text = request.lower()
    matches = list(re.finditer(r"\b(?:if|when|whenever)\b", text))
    if len(matches) > 1:
        return ""  # Do not assign fields across multiple rules.
    if matches:
        condition = text[matches[0].end() :]
        parts = re.split(r"[,;!?]|\.(?!\d)|\bthen\b", condition, maxsplit=1)
        text = text[: matches[0].start()] + (" " + parts[1] if len(parts) > 1 else "")
    # Only retain directive clauses, not an introductory description of a mode.
    clauses = re.split(r"[;!?]|\.(?!\d)|\bbut\b", text)
    directive = r"\b(?:turn|switch|start|activate|stop|halt|set|use|select|choose|keep|retain\w*|preserve|leave|maintain)\b|\b(?:heat|warm|cool)\s+(?:the |this |my )?room\b"
    return ". ".join(c for c in clauses if re.search(directive, c))


def _explicit_mode(context, device):
    field = "cleaningMode" if device == "robotVacuum" else "mode"
    modes = {
        "ac": {"heat": r"heat(?:ing)?", "cool": r"cool(?:ing)?"},
        "waterHeater": {"heating": r"heating", "keep_warm": r"keep[ _-]warm"},
        "robotVacuum": {"standard": r"standard", "quiet": r"quiet", "turbo": r"turbo"},
        "airPurifier": {"auto": r"auto(?:matic)?", "manual": r"manual"},
    }.get(device, {})
    found = set()
    for value, pattern in modes.items():
        if re.search(
            r"\b(?:"
            + pattern
            + r")\s+(?:cleaning\s+)?mode\b|\bmode\s+(?:to\s+)?(?:"
            + pattern
            + r")\b",
            context,
        ):
            found.add(value)
    if device == "ac":
        if re.search(r"\b(?:heat|warm)\s+(?:the |this |my )?room\b", context):
            found.add("heat")
        if re.search(r"\bcool\s+(?:the |this |my )?room\b", context):
            found.add("cool")
    # Coordinated values may share their trailing "mode": heat or cool mode.
    # Treat both as alternatives rather than silently selecting the last one.
    if re.search(r"\b(?:or|either|versus|vs)\b", context) and re.search(
        r"\bmode\b", context
    ):
        alternatives = {
            value
            for value, pattern in modes.items()
            if re.search(r"\b(?:" + pattern + r")\b", context)
        }
        if len(alternatives) > 1:
            found.update(alternatives)
    return field, found


def _schema_field_valid(value, spec):
    if not isinstance(spec, str):
        return False
    if "|" in spec:
        return isinstance(value, str) and value in spec.split("|")
    match = re.fullmatch(r"int\[(-?\d+)\.\.(-?\d+)\]", spec)
    return bool(
        match
        and isinstance(value, int)
        and not isinstance(value, bool)
        and int(match[1]) <= value <= int(match[2])
    )


def _explicit_constraints(request, state, output):
    """Input-only targets for uniquely scoped, explicitly named fields.

    A field is retained only when the user says to retain it. No blanket copying
    of state and no inference of an arbitrary temperature from a comfort word.
    """
    text = request.lower()
    named = [d for d, p in DEVICE_ALIASES.items() if re.search(p, text)]
    if len(named) != 1:
        return {}, set()
    device = named[0]
    context = _action_context(request)
    if not context or re.search(
        r"\b(?:do not|don.t|never|not|avoid|unless|instead of)\b", context
    ):
        return {}, set()
    # Existing valid rules may get parameter checks, but their family is kept.
    registry = base.build_model_input(
        {
            "input": {
                "userInstruction": request,
                "current_state": state,
                "timestamp": "00:00:00",
            }
        }
    )["capability_registry"]["device_parameters"]
    specs = registry.get(device, {})
    targets = {}
    blocked = set()
    retention = []
    for clause in re.split(r"[.;!?]|\bbut\b", context):
        if re.search(r"\b(?:or|either|versus|vs)\b", clause) and not re.search(
            r"\bwithout changing\b", clause
        ):
            continue  # Retain target OR fan speed does not name a unique subset.
        if re.search(
            r"\b(?:keep|retain\w*|preserve|leave|maintain)\b|\bwithout changing\b",
            clause,
        ) and re.search(
            r"\b(?:current|existing|saved|unchanged|alone|same)\b|\bas is\b|\bwithout changing\b",
            clause,
        ):
            retention.append(clause)
    mode_field, modes = _explicit_mode(context, device)
    for path, action in _actions(output):
        if action.get("deviceId") != device or not isinstance(
            action.get("parameters"), dict
        ):
            continue
        params = action["parameters"]
        saved = state.get(device, {})
        if not isinstance(saved, dict):
            saved = {}
        for field, pattern in RETAINABLE_FIELDS.get(device, {}).items():
            field_path = path + ("parameters", field)
            if field not in params or not any(re.search(pattern, c) for c in retention):
                continue
            # Explicit new numbers beat state inheritance for that field.
            if _number_target(context, device, field) is not None:
                continue
            value = saved.get(field)
            if _schema_field_valid(value, specs.get(field)):
                targets[field_path] = (
                    copy.deepcopy(value),
                    "explicit_named_state_retention",
                )
        mode_path = path + ("parameters", mode_field)
        if mode_field not in params or action.get("action") != "turn_on":
            continue
        if len(modes) > 1:
            targets.pop(mode_path, None)
            blocked.add(mode_path)
        elif len(modes) == 1:
            mode = next(iter(modes))
            if mode_path in targets and targets[mode_path][0] != mode:
                # Conflicting same-field requests are not resolved by guessing.
                targets.pop(mode_path, None)
                blocked.add(mode_path)
            elif _schema_field_valid(mode, specs.get(mode_field)):
                targets[mode_path] = (mode, "explicit_requested_device_mode")
    return targets, blocked


def repair_plan(request, state, output):
    operations = _state_repair_plan(request, state, output)
    targets, blocked = _explicit_constraints(request, state, output)
    # Explicit decisions suppress conflicting state-derived defaults even if the
    # initial already satisfies the request (and therefore needs no patch).
    operations = [
        op
        for op in operations
        if tuple(op["path"]) not in targets and tuple(op["path"]) not in blocked
    ]
    for path, (value, basis) in targets.items():
        old = _get(output, path)
        if old != value:
            operations.append(
                {"path": list(path), "old": old, "target": value, "basis": basis}
            )
    return operations


def candidate_acceptable(initial, candidate, allowed_paths, route_mode=None):
    if not isinstance(candidate, dict):
        return False, "missing_candidate"
    if initial is None:
        family = outcome_family(candidate)
        if route_mode == "rule" and family != "rule":
            return False, "route_family_changed"
        if route_mode == "ordinary" and family == "rule":
            return False, "route_family_changed"
        return True, "accepted_valid_schema_recovery"
    if outcome_family(initial) != outcome_family(candidate):
        return False, "outcome_family_changed"
    if action_identities(initial) != action_identities(candidate):
        return False, "action_identity_changed"
    changes = _differences(initial, candidate)
    # Message wording is not a parameter repair; keep it unchanged as well.
    if not changes.issubset({tuple(p) for p in allowed_paths}):
        return False, "unaffected_field_changed"
    return True, "accepted_minimal_changes"


def _prompt(request, state, timestamp, output, structural, operations, route_mode):
    context = base.build_model_input(
        {
            "input": {
                "userInstruction": request,
                "current_state": state,
                "timestamp": timestamp,
            }
        },
        outcome=route_mode,
    )
    return (
        "Repair one JSON representation. Return only JSON.\n"
        "Preserve outcome, device/action identities, message and every unaffected field.\n"
        "Only repair the listed paths. Missing parameters must preserve normalized values.\n"
        "Explicit user values override default conventions. Do not invent thresholds or reset settings.\n"
        "Context:\n"
        + json.dumps(context, ensure_ascii=False)
        + "\nInitial:\n"
        + json.dumps(output, ensure_ascii=False)
        + "\nStructural diagnostics:\n"
        + json.dumps(structural, ensure_ascii=False)
        + "\nGrounded operations:\n"
        + json.dumps(operations, ensure_ascii=False)
    )


def _repair_core(
    request, state, timestamp, initial, candidate_generator=None, route_mode=None
):
    """Apply checked deterministic repairs, then at most one bounded model call."""
    output = copy.deepcopy(initial.get("output"))
    structural = copy.deepcopy(initial.get("checker_diagnostics") or [])
    operations = repair_plan(request, state, output)
    triggered = bool(structural or operations)
    final = copy.deepcopy(initial)
    candidate = None
    accepted = False
    reason = "repair_not_triggered"
    prompt = None
    calls = 0
    if not triggered:
        return {
            "protocol": PROTOCOL_ID,
            "initial": initial,
            "candidate": None,
            "final": final,
            "triggered": False,
            "accepted": False,
            "reason": reason,
            "operations": [],
            "structural": structural,
            "model_calls": 0,
            "prompt": None,
        }
    proposed = copy.deepcopy(output)
    if isinstance(proposed, dict):
        for op in operations:
            _set(proposed, tuple(op["path"]), op["target"])
        candidate = base.validate_model_output(
            json.dumps(proposed, ensure_ascii=False), state
        )
        if candidate["checker_passed"]:
            accepted, reason = candidate_acceptable(
                output,
                candidate["output"],
                [op["path"] for op in operations],
                route_mode,
            )
            if accepted:
                final = candidate
                reason = (
                    "accepted_grounded_patch"
                    if operations
                    else "accepted_normalized_parameter_completion"
                )
    if not accepted and candidate_generator is not None:
        prompt = _prompt(
            request, state, timestamp, output, structural, operations, route_mode
        )
        raw = candidate_generator(prompt)
        calls = 1
        candidate = base.validate_model_output(raw, state)
        if candidate["checker_passed"]:
            accepted, reason = candidate_acceptable(
                output,
                candidate["output"],
                [op["path"] for op in operations],
                route_mode,
            )
            if accepted:
                # A legal candidate must also satisfy the grounded operations.
                if any(
                    _get(candidate["output"], tuple(op["path"])) != op["target"]
                    for op in operations
                ):
                    accepted = False
                    reason = "grounded_target_not_satisfied"
                else:
                    final = candidate
        else:
            reason = "candidate_failed_checker"
    return {
        "protocol": PROTOCOL_ID,
        "initial": initial,
        "candidate": candidate,
        "final": final,
        "triggered": triggered,
        "accepted": accepted,
        "reason": reason,
        "operations": operations,
        "structural": structural,
        "model_calls": calls,
        "prompt": prompt,
    }
