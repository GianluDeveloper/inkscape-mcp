# Batch Inkscape + HTTP MCP. Desktop sessions stay on the host.
# docker build --network=host --target production -t inkscape-mcp:local .
# docker run --rm -p 127.0.0.1:10900:10900 -p 127.0.0.1:9074:9074 inkscape-mcp:local

FROM ghcr.io/astral-sh/uv:0.12.16@sha256:adc68cd785ca65ea25c0611043b0a00b4ea3a22e1b54102fc084406d888082ee AS uv

# PyGObject in uv.lock requires girepository-2.0 (Ubuntu 24.04 is too old).
FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78 AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates inkscape libmagic1t64 fonts-dejavu-core \
        libcairo2 libgirepository-2.0-0 gir1.2-gtk-3.0 libglib2.0-bin \
    && rm -rf /var/lib/apt/lists/*

FROM base AS build

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential pkg-config python3-dev libcairo2-dev libgirepository-2.0-dev \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE NOTICE.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev --extra monitoring --no-editable --python 3.12.14 \
    && /opt/venv/bin/python -c "import gi, cairo, inkex, inkscape_mcp.main"

FROM base AS production

COPY --from=build /opt/python /opt/python
COPY --from=build /opt/venv /opt/venv

# Native Inkscape effects use system Python, independently of the MCP venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-numpy python3-lxml python3-scour python3-cssselect python3-platformdirs \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/bin/python3 -c "import sys; sys.path.insert(0, '/usr/share/inkscape/extensions'); import inkex"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INKSCAPE_PATH=/usr/bin/inkscape \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=10900 \
    MCP_TRANSPORT=http \
    PROMETHEUS_PORT=9074 \
    INKSCAPE_MCP_METRICS_ENABLED=true \
    INKSCAPE_MCP_LOG_FORMAT=json \
    INKSCAPE_MCP_LOG_LEVEL=INFO

RUN useradd --uid 10001 --user-group --create-home --shell /bin/bash mcp \
    && mkdir -p /app/logs /data \
    && chown -R mcp:mcp /app /data

WORKDIR /app
USER mcp

EXPOSE 10900 9074

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('MCP_PORT', '10900') + '/api/health', timeout=5)"

CMD ["inkscape-mcp"]

ARG BUILD_DATE
ARG VERSION
ARG VCS_REF

LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="Inkscape MCP" \
      org.opencontainers.image.description="Inkscape MCP server for isolated batch operations over HTTP" \
      org.opencontainers.image.source="https://github.com/GianluDeveloper/inkscape-mcp" \
      org.opencontainers.image.licenses="MIT"
