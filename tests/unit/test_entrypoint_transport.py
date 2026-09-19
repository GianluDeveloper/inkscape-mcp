"""Protect stdio launches, environment overrides, and packaged bootstraps."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

import inkscape_mcp.main as main_module
from inkscape_mcp.config import InkscapeConfig
from inkscape_mcp.transport import resolve_config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "environment", "expected"),
    [
        ([], {}, ("stdio", "127.0.0.1", 11027)),
        ([], {"MCP_TRANSPORT": "stdio", "MCP_PORT": "12345"}, ("stdio", "127.0.0.1", 12345)),
        (
            [],
            {"MCP_TRANSPORT": "http", "MCP_PORT": "23456", "MCP_HOST": "127.0.0.2"},
            ("http", "127.0.0.2", 23456),
        ),
        (
            ["--mode=http", "--host", "127.0.0.3", "--port", "34567"],
            {"MCP_TRANSPORT": "stdio", "MCP_PORT": "12345", "MCP_HOST": "127.0.0.2"},
            ("http", "127.0.0.3", 34567),
        ),
        (["--mode", "stdio"], {"MCP_TRANSPORT": "http"}, ("stdio", "127.0.0.1", 11027)),
    ],
)
async def test_main_preserves_transport_precedence(monkeypatch, arguments, environment, expected):
    for name in ("MCP_TRANSPORT", "MCP_HOST", "MCP_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["inkscape-mcp", *arguments])
    server = Mock(initialize=AsyncMock(return_value=True))
    monkeypatch.setattr(main_module, "InkscapeMCPServer", Mock(return_value=server))
    runner = AsyncMock()
    monkeypatch.setattr(main_module, "run_server_async", runner)
    monkeypatch.setattr(main_module.logging, "basicConfig", Mock())

    assert await main_module.main_async() == 0

    config = resolve_config(runner.call_args.kwargs["args"])
    assert (config["transport"], config["host"], config["port"]) == expected


@pytest.mark.asyncio
async def test_explicit_executable_survives_initialization(
    monkeypatch, mock_inkscape_path, tmp_path
):
    config_file = tmp_path / "config.yaml"
    config = InkscapeConfig(inkscape_executable=str(mock_inkscape_path), process_timeout=45)
    config.save_to_file(config_file)
    detector = Mock(side_effect=AssertionError("Explicit configuration must not be replaced"))
    monkeypatch.setattr(main_module.InkscapeDetector, "detect_inkscape_installation", detector)
    monkeypatch.setenv("INKSCAPE_MCP_METRICS_ENABLED", "false")
    server = main_module.InkscapeMCPServer(config_file)

    assert await server.initialize() is True
    assert server.cli_wrapper.config.inkscape_executable == str(mock_inkscape_path)
    assert server.cli_wrapper.config.process_timeout == 45
    detector.assert_not_called()


def test_main_loads_default_config_file(monkeypatch, tmp_path, mock_inkscape_path):
    monkeypatch.chdir(tmp_path)
    config = InkscapeConfig(inkscape_executable=str(mock_inkscape_path), process_timeout=47)
    config.save_to_file(tmp_path / "config.yaml")

    server = main_module.InkscapeMCPServer()

    assert server.config.process_timeout == 47
    assert server.config.inkscape_executable == str(mock_inkscape_path)


@pytest.mark.parametrize("launcher", ["run_server.py", "mcpb/run_server.py"])
@pytest.mark.parametrize("verify_only", [False, True])
def test_launcher_uses_own_source_and_is_safe_to_import(tmp_path, launcher, verify_only):
    repo = Path(__file__).resolve().parents[2]
    bundle = tmp_path / "bundle"
    package = bundle / "src" / "inkscape_mcp"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "main.py").write_text(
        "import json, os, sys\n"
        "def main():\n"
        "    print(json.dumps({'origin': __file__, 'args': sys.argv[1:], "
        "'transport': os.environ.get('MCP_TRANSPORT'), 'port': os.environ.get('MCP_PORT')}))\n"
        "    return 7\n",
        encoding="utf-8",
    )
    entry = bundle / "run_server.py"
    shutil.copyfile(repo / launcher, entry)
    cwd = tmp_path / "unrelated-working-directory"
    cwd.mkdir()
    environment = os.environ.copy()
    environment.update(MCP_TRANSPORT="stdio", MCP_PORT="23456")
    if verify_only:
        command = [
            sys.executable,
            "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='__mcpb_verify__')",
            str(entry),
        ]
    else:
        command = [sys.executable, str(entry), "--config", "custom.yaml"]

    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=15
    )

    assert result.returncode == (0 if verify_only else 7), result.stderr
    if verify_only:
        assert result.stdout == ""
    else:
        payload = json.loads(result.stdout)
        assert Path(payload["origin"]) == package / "main.py"
        assert payload["args"] == ["--config", "custom.yaml"]
        assert payload["transport"] == "stdio"
        assert payload["port"] == "23456"
    assert list(cwd.iterdir()) == []
