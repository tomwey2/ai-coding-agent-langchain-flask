# Autonomous Containerized AI Coding Agent

![Status](https://img.shields.io/badge/Status-POC-yellow)
![Tech](https://img.shields.io/badge/Built%20With-LangGraph%20%7C%20Mistral%20%7C%20MCP-blue)

This project demonstrates a POC for an autonomous, containerized AI coding agent that lives in your Docker environment. 
It operates completely unsupervised to:

- **Connect** to your task management system
- **Pick up** open tickets automatically
- **Analyze/Write** code or fix bugs
- **Push** changes via pull requests to GitHub

## Solve the Talent Bottleneck with Artificial Developers
Modern software is complex. It relies on the collaboration of specialized teams across backend, frontend, database, 
security, and more. Every developer is a vital link in the value chain.

But what happens when resources become a bottleneck? **The solution? Simply augment your team with artificial developers working autonomously—seamlessly integrated via Jira tickets and pull requests.**

<img src="./process.png" title="AI Coding Agent Process" alt="AI Coding Agent Process" width="50%">

## Key Features

* **Multi-Agent Architecture:** Uses **LangGraph** to route tasks to specialized sub-agents (`Coder`, `Bugfixer`, `Analyst`).
* **Autonomous Git Operations:** Clones, branches, stages, commits, and pushes code using the **Model Context Protocol (MCP)** and local Git tools.
* **Task Management Integration:** Polls an external TaskApp via REST API to find work and report status updates.
* **Robust AI Logic:** Features an advanced "Anti-Freeze" system with retry loops and prompt injections to prevent LLM hallucinations or stalling.
* **Dockerized:** Runs in a secure, isolated container environment.

## Architecture

The system is built upon a stateful graph architecture:

1.  **Router Node:** Analyzes the incoming task and selects the best strategy.
2.  **Specialist Nodes:**
    * **👨‍💻 Coder:** Implements new features and writes code.
    * **🐛 Bugfixer:** Analyzes errors and applies minimal fixes.
    * **🧐 Analyst:** Read-only mode for code reviews and questions.
3.  **Tool Execution:** The agents utilize a hybrid toolset (MCP for analysis, Local Python for file I/O and Push).
4.  **Correction Loop:** If the AI fails to use tools or provides empty responses, a correction node forces it back on track.

## Tech Stack

* **Core:** Python 3.11+
* **Orchestration:** [LangGraph](https://langchain-ai.github.io/langgraph/)
* **AI Model:** Mistral Large (`mistral-large-latest`) via LangChain
* **Protocol:** [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) (Git Server)
* **Infrastructure:** Docker & UV (Package Manager)
* **Backend:** Flask, SQLAlchemy, APScheduler

---

## Getting Started

### Prerequisites

* **Docker** installed on your machine.
* A **Mistral AI API Key** (requires a subscription/credits).
* A **GitHub Personal Access Token** (Classic) with `repo` scope.
* A running Task Management API (or a mock server).

### 1. Build the Image

```bash
docker build -t coding-agent .
```

### 2. Run the Container
You must pass your API keys as environment variables.

```bash
docker run \
  -e MISTRAL_API_KEY="your_mistral_api_key" \
  -e GITHUB_TOKEN="your_github_pat" \
  -p 5000:5000 \
  -v $(pwd)/instance:/app/instance \
  coding-agent
```
