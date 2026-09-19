# Third-party attribution

## Base project

This repository continues [sandraschi/inkscape-mcp](https://github.com/sandraschi/inkscape-mcp).
The inherited project is licensed under the MIT License, copyright ©2026 Sandra
Schipal. Its license is retained in [LICENSE](LICENSE).

## Native Inkscape extension

The bundled `src/inkscape_mcp/plugins/mcp_edit_xml.py` adapts the native inkex
editing effect from [aravindev/inkscape_mcp](https://github.com/aravindev/inkscape_mcp),
reviewed at commit [5a53f76](https://github.com/aravindev/inkscape_mcp/commit/5a53f76).
The extension keeps the upstream copyright and full MIT notice in its source.
This integration adds append-only SVG requests, target checks, request IDs,
expiration/cancellation handling, and coordination between processes.

The associated native effect descriptor and design draw on the same upstream.
The managed-session and action-catalog helpers in this repository are independent
implementations informed by that review. See
[Upstream integration](docs/UPSTREAM_INTEGRATION.md) for design boundaries.

The upstream license is reproduced below:

```text
MIT License

Copyright (c) 2026 Aravind EV

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Other dependencies retain their own licenses; this notice does not replace the
license metadata distributed by those packages.
