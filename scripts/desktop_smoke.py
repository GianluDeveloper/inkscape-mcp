#!/usr/bin/env python3
"""Exercise real MCP stdio, native editing, two GUI sessions, saves and exports.

Run on a desktop, or under `dbus-run-session -- xvfb-run -a ...` for isolation.
Creates only named documents below --output-dir. Does not touch existing windows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from PIL import Image


async def exercise(output_dir: Path, keep_open: bool = False) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="desktop-smoke-", dir=output_dir))
    repo = Path(__file__).resolve().parents[1]
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "inkscape_mcp.main", "--mode", "stdio"],
        cwd=str(repo),
        env=dict(os.environ),
        keep_alive=False,
    )
    records = []
    sessions = []
    report = {
        "success": False,
        "output_dir": str(run_dir),
        "sessions": sessions,
        "kept_open": keep_open,
        "checks": records,
    }

    def checkpoint():
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    checkpoint()
    async with Client(transport, timeout=60) as client:

        async def call(operation: str, **kwargs):
            result = await client.call_tool("inkscape_system", {"operation": operation, **kwargs})
            data = result.data
            records.append(
                {
                    "operation": operation,
                    "session_id": kwargs.get("session_id"),
                    "success": bool(data.get("success")),
                    **({"error": data} if not data.get("success") else {}),
                }
            )
            checkpoint()
            if not data.get("success"):
                raise RuntimeError(f"{operation}: {data.get('error') or data.get('message')}")
            return data["data"]

        await call("install_live_extension")
        for name in ("A", "B"):
            target = await call("new_document", output_path=str(run_dir / f"document-{name}.svg"))
            sessions.append(target)
        labels = ["Documento A <&> — MCP", "Documento B — MCP"]
        for target, label in zip(sessions, labels, strict=True):
            inserted = await call("draw_test", session_id=target["session_id"], text=label)
            assert inserted["verified"] and inserted["inserted_count"] == 2
        for target, label in zip(sessions, labels, strict=True):
            live = await call("active_document", session_id=target["session_id"])
            texts = [obj["text"] for obj in live["objects"] if obj["type"] == "text"]
            assert texts == [label], f"Wrong document was modified: {texts}"
            assert live["object_count"] == 2
            disk = ET.parse(target["input_path"]).getroot()
            assert disk.find(".//{http://www.w3.org/2000/svg}rect") is None, (
                "Edits must remain unsaved until requested"
            )

        copy_dir = run_dir / "copies"
        copy_dir.mkdir()
        await call(
            "save_copy",
            session_id=sessions[0]["session_id"],
            output_path=str(copy_dir / "document-A.svg"),
        )
        for target, label in zip(sessions, labels, strict=True):
            await call("save_document", session_id=target["session_id"])
            disk = ET.parse(target["input_path"]).getroot()
            texts = ["".join(el.itertext()) for el in disk.iter("{http://www.w3.org/2000/svg}text")]
            assert texts == [label]
            png = Path(target["input_path"]).with_suffix(".png")
            result = await client.call_tool(
                "inkscape_file",
                {
                    "operation": "convert",
                    "input_path": target["input_path"],
                    "output_path": str(png),
                    "format": "png",
                },
            )
            assert result.data["success"], result.data
            with Image.open(png) as preview:
                preview.verify()
            records.append({"operation": "convert", "success": True, "output": str(png)})
        # Independent processes must remain addressable after edits and exports.
        listed = await call("list_documents")
        live_ids = {doc["session_id"] for doc in listed["documents"]}
        assert all(doc["session_id"] in live_ids for doc in sessions)
        if not keep_open:
            for target in reversed(sessions):
                await call("close_document", session_id=target["session_id"])
            listed = await call("list_documents")
            live_ids = {doc["session_id"] for doc in listed["documents"]}
            assert all(doc["session_id"] not in live_ids for doc in sessions)
    report["success"] = True
    checkpoint()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--keep-open", action="store_true", help="Leave the two saved demo windows open"
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(exercise(args.output_dir.resolve(), args.keep_open)), indent=2))


if __name__ == "__main__":
    main()
