FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install Node.js for MCP servers
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN uv venv \
    && uv pip install -r requirements.txt

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/app

# Copy production config file
COPY ./msc/mcp.json /app/mcp.json

# Start app

CMD ["python", "main.py", "start", "--transport", "sse", "--config", "mcp.json", "--host", "0.0.0.0"]
