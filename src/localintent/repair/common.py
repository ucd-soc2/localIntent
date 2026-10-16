"""Reference-free action identity and diagnostic helpers."""


def structured_diagnostics(diagnostics: list[dict]) -> list[dict]:
    return [
        {
            key: item.get(key)
            for key in ("code", "path", "message", "received", "allowed")
        }
        for item in diagnostics
        if isinstance(item, dict)
    ]


def outcome_family(output):
    if not isinstance(output, dict):
        return None
    if isinstance(output.get("rule"), dict):
        return "rule"
    if output.get("needsClarification") is True:
        return "clarification"
    if isinstance(output.get("result"), list) and output["result"]:
        return "command"
    if isinstance(output.get("result"), list):
        return "rejection"
    return None


def action_identities(output):
    if not isinstance(output, dict):
        return []
    if isinstance(output.get("rule"), dict):
        action = output["rule"].get("action")
        return (
            []
            if not isinstance(action, dict)
            else [(action.get("deviceId"), action.get("action"))]
        )
    return [
        (item.get("deviceId"), item.get("action"))
        for item in output.get("result", [])
        if isinstance(item, dict)
    ]
