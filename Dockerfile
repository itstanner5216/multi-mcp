FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install Node.js for MCP servers
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN uv venv \
    && uv pip install -r requirements.txt

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/app

# Copy production config file if it exists
RUN test -f ./msc/mcp.json && cp ./msc/mcp.json /app/mcp.json || true

RUN addgroup --system appuser \
    && adduser --system --ingroup appuser appuser \
    && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD curl -f http://localhost:8083/health || exit 1

# Start app

CMD ["python", "main.py", "start", "--transport", "sse", "--config", "mcp.json", "--host", "0.0.0.0"]
