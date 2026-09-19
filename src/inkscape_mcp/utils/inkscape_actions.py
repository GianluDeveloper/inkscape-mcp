"""Validation for action strings shared by CLI, shell and live GUI operations."""

from __future__ import annotations


def validate_actions(actions: list[str] | str) -> list[str]:
    """Reject internal bridge actions which can crash Inkscape's document saver.

    Inkscape itself manages active-window-start/end around --active-window.
    Calling them explicitly can dereference an absent document (upstream #4765).
    Action strings have no escaping for line breaks or NUL characters.
    """
    entries = [actions] if isinstance(actions, str) else actions
    result = []
    for entry in entries:
        if not isinstance(entry, str) or any(c in entry for c in "\x00\r\n"):
            raise ValueError("Inkscape actions must be strings without NUL or line breaks")
        for action in entry.split(";"):
            action = action.strip()
            name = action.partition(":")[0].strip().removeprefix("app.")
            if name in {"active-window-start", "active-window-end"}:
                raise ValueError(
                    f"{name} is an internal Inkscape action and can crash document saving. "
                    "Use file-based operations or hands_in_command without internal bridge actions."
                )
            if action:
                result.append(action)
    return result
