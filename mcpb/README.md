# inkscape-mcp (MCPB Bundle)

MCP server for Inkscape-backed SVG and vector operations (FastMCP 3.2.0+)

## Usage

Add to \claude_desktop_config.json\:
\\\json
{
  "mcpServers": {
    "inkscape-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "\D:\Dev\repos", "python", "-m", "inkscape_mcp"],
      "env": { "PYTHONPATH": "\D:\Dev\repos/src" }
    }
  }
}
\\\

## Tools

- **generate_svg**: generate_svg
- **agentic_inkscape_workflow**: agentic_inkscape_workflow
- **intelligent_vector_processing**: intelligent_vector_processing
- **conversational_inkscape_assistant**: conversational_inkscape_assistant
- **api_logs**: api_logs
- **api_logs_clear**: api_logs_clear
- **api_help**: api_help
- **api_docs**: api_docs
- **llm_providers**: llm_providers
- **health**: health
- **diagnostics**: diagnostics
- **system_info**: system_info
- **generate_svg_endpoint**: generate_svg_endpoint
- **api_v1_tool**: api_v1_tool
- **list_skills**: list_skills
- **get_skill**: get_skill
- **fleet_overview**: fleet_overview
- **capabilities**: capabilities
- **main_stdio**: main(stdio)
- **main_http**: main(http)
- **main_sse**: main(sse)
- **list_local_models**: list_local_models
- **inkscape_analysis_quality**: inkscape_analysis(quality)
- **inkscape_analysis_statistics**: inkscape_analysis(statistics)
- **inkscape_analysis_validate**: inkscape_analysis(validate)
- **inkscape_analysis_objects**: inkscape_analysis(objects)
- **inkscape_analysis_dimensions**: inkscape_analysis(dimensions)
- **inkscape_analysis_structure**: inkscape_analysis(structure)
- **inkscape_file_load**: inkscape_file(load)
- **inkscape_file_save**: inkscape_file(save)
- **inkscape_file_convert**: inkscape_file(convert)
- **inkscape_file_info**: inkscape_file(info)
- **inkscape_file_validate**: inkscape_file(validate)
- **inkscape_file_list_formats**: inkscape_file(list_formats)
- **generate_heraldry**: generate_heraldry
- **generate_heraldry_trumponia_trumponia**: generate_heraldry_trumponia(trumponia)
- **generate_heraldry_trumponia_custom**: generate_heraldry_trumponia(custom)
- **_parse_svg_xml_list**: _parse_svg_xml(list)
- **_parse_svg_xml_get**: _parse_svg_xml(get)
- **_parse_svg_xml_create**: _parse_svg_xml(create)
- **_parse_svg_xml_rename**: _parse_svg_xml(rename)
- **_parse_svg_xml_hide**: _parse_svg_xml(hide)
- **_parse_svg_xml_show**: _parse_svg_xml(show)
- **_parse_svg_xml_reorder**: _parse_svg_xml(reorder)
- **_parse_svg_xml_lock**: _parse_svg_xml(lock)
- **_parse_svg_xml_unlock**: _parse_svg_xml(unlock)

## Requirements

- Python 3.12+
- uv
