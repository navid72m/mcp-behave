FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    strace curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*
# Node.js 22 LTS — for npx-based MCP servers
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
# uv — for uvx-based MCP servers
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
WORKDIR /app
# Pre-install real MCP servers as REAL modules so the probe traces the running
# server directly, not a uvx/npx downloader. Tracing through uvx/npx pollutes
# the profile with package-manager network + filesystem activity.
RUN pip install --no-cache-dir mcp-server-fetch
COPY . .
# Install mcp-behave itself (and its deps from pyproject.toml).
RUN pip install --no-cache-dir .
# Run inside the repo so planted canaries in ./sandbox_home are used as $HOME.
ENTRYPOINT ["bash", "run.sh"]