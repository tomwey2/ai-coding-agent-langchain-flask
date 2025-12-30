FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /coding-agent

# 1. System-Pakete installieren
RUN apt-get update && apt-get install -y \
    git \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# 2. 'uv' und 'tsx' installieren
RUN pip install uv
RUN npm install -g tsx

# 3. Dependencies installieren
COPY pyproject.toml uv.lock ./

# Installiere Abhängigkeiten ins System-Python
RUN uv sync --frozen --no-install-project

# 4. Trello-Server vorbereiten
RUN mkdir -p /coding-agent/servers && \
    git clone https://github.com/lioarce01/trello-mcp-server.git /coding-agent/servers/trello && \
    cd /coding-agent/servers/trello && \
    npm install

# 5. Code kopieren
COPY . .

# 6. Git Dummy-Config (damit der Agent committen kann)
RUN git config --global user.email "agent@bot.local" && \
    git config --global user.name "AI Coding Agent" && \
    git config --global safe.directory "/coding-agent-workspace"

# 7. Startbefehl
CMD ["uv", "run", "app/main.py"]
