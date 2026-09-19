"""Discover the installed Inkscape CLI action surface without editing documents.

The searchable descriptions are inspired by aravindev/inkscape_mcp's live action
catalog. This implementation uses the configured CLI wrapper and adds bounded
pagination; it does not assume that CLI actions are also exposed over D-Bus.
"""

from __future__ import annotations

import re
from typing import Any

from ..cli_wrapper import InkscapeExecutionError
from ..config import InkscapeConfig

_ACTION_LINE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$")


def parse_action_catalog(output: str) -> list[dict[str, str]]:
    """Parse CLI name/description rows, preserving colons inside descriptions."""
    descriptions: dict[str, str] = {}
    for line in output.splitlines():
        match = _ACTION_LINE.fullmatch(line.strip())
        if match:
            name, description = match.groups()
            descriptions[name] = description.strip()
    return [
        {"name": name, "description": descriptions[name]}
        for name in sorted(descriptions, key=str.casefold)
    ]


async def list_actions(
    *,
    cli_wrapper: Any,
    config: InkscapeConfig | None,
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a searchable page from this executable's current action catalog."""
    if not isinstance(search, str):
        raise ValueError("search must be a string")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer between 1 and 500")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    if config is None or not config.inkscape_executable or cli_wrapper is None:
        raise InkscapeExecutionError("Inkscape CLI is unavailable; configure INKSCAPE_PATH first")

    executable = str(config.inkscape_executable)
    output = await cli_wrapper._execute_command(
        [executable, "--action-list"], config.process_timeout
    )
    catalog = parse_action_catalog(output)
    if not catalog:
        raise InkscapeExecutionError("Inkscape returned no recognizable CLI actions")

    needle = search.strip().casefold()
    matches = [
        item
        for item in catalog
        if needle in item["name"].casefold() or needle in item["description"].casefold()
    ]
    page = matches[offset : offset + limit]
    has_more = offset + len(page) < len(matches)
    return {
        "actions": page,
        "total_actions": len(catalog),
        "matched_actions": len(matches),
        "returned": len(page),
        "search": search,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + len(page) if has_more else None,
        "source": "inkscape --action-list",
        "scope": "cli",
        "executable": executable,
        "note": "CLI discovery does not guarantee headless execution or live D-Bus availability.",
    }
