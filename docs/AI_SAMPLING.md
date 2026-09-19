# Sampling and optional model services

Ordinary SVG construction, file edits, export, inspection, and live drawing use
normal MCP tool calls. They do not need a separate model service or client sampling.

## Client sampling

Four tools in `agentic.py` call FastMCP's `Context.sample()`:

- `generate_svg`: requests SVG XML and saves the result beneath `generated_svgs/`.
- `agentic_inkscape_workflow`: returns an ordered workflow plan.
- `intelligent_vector_processing`: returns a processing plan for documents.
- `conversational_inkscape_assistant`: returns vector graphics guidance.

The MCP client must support sampling **and** `sampling.tools`, since the model
can consult capability probes. FastMCP injects `Context`; never provide `ctx` as a
JSON argument. Registration of these tools does not prove the client implements
the capability.

Planning helpers do not automatically execute every edit described in their
responses. Verify proposed operations against `tools/list`, then call the editing
tools. Validate generated XML before using it in downstream rendering or sharing.

If sampling is unavailable, construct SVG directly:

```json
{
  "operation": "construct_svg",
  "output_path": "/absolute/path/to/simple.svg",
  "svg_content": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\"><circle cx=\"50\" cy=\"50\" r=\"30\" fill=\"blue\"/></svg>"
}
```

Send that request to `inkscape_vector`.

## Dashboard providers

The optional HTTP dashboard has a separate generation path using Ollama and
configured cloud fallbacks. `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and provider keys
apply to that path; they do not add sampling capability to an MCP client.

`list_local_models` discovers reachable local model endpoints. `llm_ops` can
inspect or change the local engine's loaded models. These services are optional.
See [Configuration](CONFIGURATION.md) and [Tools](TOOLS.md).
