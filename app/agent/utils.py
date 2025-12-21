import logging
import os
import re
import shutil

from git import Repo
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


def load_system_prompt(stack: str, role: str) -> str:
    """
    Lädt den System-Prompt basierend auf Stack und Rolle.
    z.B. stack="backend_java_spring", role="coder" -> liest config/java_spring/system_coder.txt
    """
    # Basis-Pfad (angepasst an deine Struktur)
    base_dir = os.path.dirname(os.path.abspath(__file__))  # Ordner der aktuellen Datei
    # Pfad zur config hoch navigieren, falls nötig. Annahme: config liegt im Root.
    project_root = os.path.dirname(base_dir)

    file_path = os.path.join(project_root, "config", stack, f"systemprompt_{role}.txt")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback, falls Datei fehlt (wichtig für Robustheit!)
        logger.warning(f"WARNUNG: System Prompt not found: {file_path}")
        return "You are a helpful coding assistent."


def sanitize_response(response: AIMessage) -> AIMessage:
    """
    Entfernt halluzinierte Tool-Calls (z.B. wenn der Name ein ganzer Satz ist).
    Verhindert API Fehler 3280 (Invalid function name).
    """
    # Wenn keine Tool Calls da sind oder es keine AI Message ist, einfach zurückgeben
    if not isinstance(response, AIMessage) or not response.tool_calls:
        return response

    valid_tools = []
    # Erlaubte Zeichen für Funktionsnamen: a-z, A-Z, 0-9, _, -
    name_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")

    for tc in response.tool_calls:
        name = tc.get("name", "")
        # Check: Ist der Name im gültigen Format und nicht zu lang?
        if name_pattern.match(name) and len(name) < 64:
            valid_tools.append(tc)
        else:
            logger.warning(f"SANITIZER: Removed invalid tool call with name: '{name}'")

    # Das manipulierte Objekt zurückgeben
    response.tool_calls = valid_tools
    return response


def save_graph_as_png(graph):
    # 1. Die Bilddaten in einer Variable speichern (es sind Bytes)
    png_bytes = graph.get_graph().draw_mermaid_png()

    # 2. Datei im 'write binary' Modus ("wb") öffnen und speichern
    with open("workflow_graph.png", "wb") as f:
        f.write(png_bytes)

    print("Graph wurde als 'workflow_graph.png' gespeichert.")


def save_graph_as_mermaid(graph):
    # 1. Die Bilddaten in einer Variable speichern (es sind Bytes)
    mermaid_code = graph.get_graph().draw_mermaid()

    # 2. Datei im 'write binary' Modus ("wb") öffnen und speichern
    with open("workflow_graph.mmd", "w") as f:
        f.write(mermaid_code)

    print("Graph wurde als 'workflow_graph.mmd' gespeichert.")


def ensure_repository_exists(repo_url, work_dir):
    """
    Stellt sicher, dass work_dir ein valides Git-Repo ist.
    """
    # 1. Inhalt löschen, aber NICHT den Ordner selbst (wegen Mount)
    for filename in os.listdir(work_dir):
        file_path = os.path.join(work_dir, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

    # 2. In das nun leere Verzeichnis klonen
    # Der Punkt '.' ist wichtig, damit git nicht einen Unterordner erstellt
    logger.info(f"Cloning repository {repo_url} into {work_dir}")
    Repo.clone_from(repo_url, work_dir)
