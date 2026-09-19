"""Discover nested, namespaced extension metadata without stale identifiers."""

from types import SimpleNamespace

from inkscape_mcp.tools.system import inkscape_system


async def test_extension_discovery_includes_custom_profile_and_parses_xml(tmp_path, monkeypatch):
    monkeypatch.setenv("INKSCAPE_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = tmp_path / "profile" / "extensions" / "nested"
    folder.mkdir(parents=True)
    (folder / "first.inx").write_text(
        '<inkscape-extension xmlns="http://www.inkscape.org/namespace/inkscape/extension">'
        '<name translatable="yes">First extension</name><id>org.test.first</id></inkscape-extension>'
    )
    (folder / "second.inx").write_text(
        "<inkscape-extension><_name>Second</_name></inkscape-extension>"
    )
    (folder / "bad.inx").write_text("<broken")
    result = await inkscape_system(
        operation="list_extensions",
        config=SimpleNamespace(inkscape_executable=tmp_path / "bin" / "inkscape"),
    )
    assert result["success"]
    entries = {item["name"]: item["id"] for item in result["data"]["extensions"]}
    assert entries == {"First extension": "org.test.first", "Second": "second"}
