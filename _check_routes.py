import sys
sys.path.insert(0, 'src')
from inkscape_mcp.app import register_rest_api
from fastmcp import FastMCP

m = FastMCP('t')
register_rest_api(m)
h = m.http_app()
for r in h.routes:
    path = getattr(r, 'path', '?')
    print(f'{type(r).__name__} path={path}')
    if hasattr(r, 'app') and hasattr(r.app, 'routes'):
        for sr in r.app.routes:
            m2 = getattr(sr, 'methods', None)
            print(f'  -> {m2} {sr.path}')
