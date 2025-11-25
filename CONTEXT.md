# Project Context: Autonomous Multi-Agent Coding System

## 1. Projektübersicht
Dieses Projekt implementiert einen autonomen **KI-Software-Entwickler**, der in einem Docker-Container läuft. Das System überwacht eine externe Task-Management-Applikation, holt sich Aufgaben, bearbeitet Code in einem Git-Repository und meldet die Ergebnisse zurück.

Die Architektur basiert auf einem **Multi-Agenten-System (MAS)**, das durch **LangGraph** gesteuert wird und das **Model Context Protocol (MCP)** für die Git-Integration nutzt.

## 2. Tech-Stack & Infrastruktur

* **Sprache:** Python 3.11+
* **Package Manager:** `uv`
* **Containerisierung:** Docker (basiert auf `python:3.11-slim`)
* **KI-Modell:** Mistral Large (`mistral-large-latest`) via `langchain-mistralai`
* **Orchestrierung:** LangGraph (Stateful Workflow Engine)
* **Tool-Schnittstelle:**
    * **MCP:** `@modelcontextprotocol/server-git` (für Git-Operationen wie status, diff, log)
    * **Local Tools:** Python-Funktionen für Dateisystemzugriff und Push.
* **Backend/UI:** Flask & Flask-SQLAlchemy (für Konfiguration und Polling-Loop).
* **Scheduler:** APScheduler (zyklisches Polling der Tasks).

## 3. Architektur: Der Multi-Agenten Graph

Das "Gehirn" des Containers ist ein gerichteter Graph (`StateGraph`), der in `agent/worker.py` definiert ist.

### A. Die Rollen (Nodes)
1.  **Router Node:** Analysiert den Task und entscheidet über die Strategie (`CODER`, `BUGFIXER`, `ANALYST`).
2.  **Coder Node:** Spezialisiert auf Feature-Implementierung. Darf Dateien erstellen und ändern.
3.  **Bugfixer Node:** Spezialisiert auf Fehlerbehebung. Analysiert zuerst, bevor geschrieben wird.
4.  **Analyst Node:** Read-Only. Darf Code lesen, aber nicht verändern.
5.  **Tool Node:** Führt die angeforderten Werkzeuge aus.
6.  **Correction Node:** Fängt Fehler ab (z.B. wenn das LLM Text statt Tools generiert) und führt den Agenten zurück auf den Pfad.

### B. Der Workflow
1.  **Start:** Task wird geladen -> Repository wird geklont (Bootstrapping).
2.  **Routing:** Entscheidung, welcher Spezialist benötigt wird.
3.  **Execution Loop:**
    * Agent "denkt" und ruft ein Tool auf.
    * Tool wird ausgeführt.
    * Ergebnis geht zurück an den Agenten.
4.  **Abschluss:** Der Agent ruft das Tool `finish_task` auf -> Graph endet -> Ergebnis wird an TaskApp gepostet.

## 4. Tools & Fähigkeiten

Der Agent verfügt über ein hybrides Tool-Set:

### A. MCP Tools (via Git Server)
Diese Tools kommen extern vom offiziellen MCP-Server:
* `git_status`, `git_diff`, `git_log` (zur Analyse).
* `git_add`, `git_commit` (zur Versionierung).

### B. Lokale Custom Tools (`agent/local_tools.py`)
Diese Tools wurden spezifisch implementiert:
* `read_file(filepath)`: Liest Dateiinhalt.
* `write_to_file(filepath, content)`: Erstellt/Überschreibt Dateien.
* `list_files(directory)`: Rekursives Listing (ohne .git).
* `git_push_origin()`: Führt den Push durch (mit Token-Injection via ENV).
* `log_thought(thought)`: Erlaubt dem Agenten, "laut zu denken" (Planung).
* `finish_task(summary)`: Signalisiert das Ende der Bearbeitung.

## 5. Wichtige Design-Entscheidungen & Fixes

### A. Token Limit
Das Modell ist auf **`max_tokens=8192`** konfiguriert. Dies ist zwingend notwendig, um auch große Dateien vollständig schreiben zu können, ohne dass das JSON abgschnitten wird (was zu Abstürzen führt).

### B. "Anti-Freeze" Strategie (Robustness)
Um zu verhindern, dass das LLM in eine Schweige-Schleife gerät (leere Antworten), implementiert der `worker.py` eine eskalierende Retry-Logik innerhalb der Nodes:
1.  **Versuch 1 (`auto`):** Standard-Verhalten.
2.  **Versuch 2 & 3 (`any`):** Bei leeren Antworten wird `tool_choice="any"` erzwungen.
3.  **Injection:** Dem Kontext wird künstlich eine Nachricht hinzugefügt ("I have planned enough, I must act now"), um die Schreibblockade des Modells zu lösen.

### C. Action-Only Prinzip
Die Prompts verbieten reines Chatten ("You are a HEADLESS agent"). Jede Interaktion muss über ein Tool erfolgen (`log_thought` für Text, `write_to_file` für Code). Dies verhindert API-Fehler bezüglich der Nachrichten-Reihenfolge.

## 6. Konfiguration & Environment

Die Steuerung erfolgt über Umgebungsvariablen und die Datenbank:
* `MISTRAL_API_KEY`: Für das LLM.
* `GITHUB_TOKEN`: Für `git push` Operationen (wird zur Laufzeit in die URL injiziert).
* **SQLite DB:** Speichert TaskApp-URL, User-Credentials und das Ziel-Projekt.

## 7. Dateistruktur

```text
/app
├── agent/
│   ├── local_tools.py    # Custom Tools (Read, Write, Push)
│   ├── mcp_adapter.py    # Verbindung zum MCP Git Server
│   ├── prompts.py        # System Prompts für alle Rollen
│   ├── task_connector.py # REST Client für TaskApp
│   ├── worker.py         # LangGraph Logik & Loop
│   └── llm_setup.py      # Mistral Konfiguration
├── templates/            # HTML Dashboard
├── main.py               # Entrypoint (Flask + Scheduler)
├── models.py             # DB Schema
├── constants.py          # Globale Konstanten
├── extensions.py         # Flask Extensions Init
├── Dockerfile            # Python Image Setup
└── pyproject.toml        # Dependencies (uv)
