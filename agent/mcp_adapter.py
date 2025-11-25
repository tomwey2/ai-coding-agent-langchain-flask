import asyncio
import os
from contextlib import AsyncExitStack

# LangChain / Pydantic Imports
from langchain_core.tools import StructuredTool

# MCP Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import Field, create_model


class McpGitAdapter:
    def __init__(self):
        # ÄNDERUNG: Wir rufen das Python-Paket direkt auf.
        # "mcp-server-git" ist das Executable, das pip/uv installiert hat.
        # Wir übergeben "--repository /app/work_dir", damit er weiß, wo er arbeiten soll.

        self.server_params = StdioServerParameters(
            command="mcp-server-git",
            args=["--repository", "/app/work_dir"],
            env=os.environ.copy(),
        )
        self.exit_stack = AsyncExitStack()
        self.session = None

    async def __aenter__(self):
        """Startet den Server und die Session."""
        # 1. Transport Layer (Stdio) starten
        read, write = await self.exit_stack.enter_async_context(
            stdio_client(self.server_params)
        )

        # 2. Session Layer starten
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )

        # 3. Initialisierung (Handshake)
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Räumt auf und stoppt den Server."""
        await self.exit_stack.aclose()

    async def get_langchain_tools(self):
        """
        Holt alle Tools vom MCP Server und konvertiert sie in LangChain Tools.
        """
        if not self.session:
            raise RuntimeError(
                "MCP Session not started. Use 'async with McpGitAdapter() ...'"
            )

        # Liste der Tools vom Server abrufen
        mcp_tools_list = await self.session.list_tools()
        langchain_tools = []

        for tool_schema in mcp_tools_list.tools:
            # Wir bauen für jedes Tool einen Wrapper
            lc_tool = self._convert_to_langchain_tool(tool_schema)
            langchain_tools.append(lc_tool)

        return langchain_tools

    def _convert_to_langchain_tool(self, tool_schema):
        """
        Wandelt ein MCP Tool Schema in ein LangChain StructuredTool um.
        """
        tool_name = tool_schema.name
        tool_desc = tool_schema.description or "No description provided."

        # 1. Dynamisches Pydantic Model für die Argumente erstellen
        # MCP liefert JSON Schema (inputSchema), LangChain will Pydantic
        fields = {}
        input_schema = tool_schema.inputSchema or {}
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        for field_name, field_info in properties.items():
            field_type = str
            json_type = field_info.get("type")

            # Einfaches Type-Mapping (kann erweitert werden)
            if json_type == "integer":
                field_type = int
            elif json_type == "boolean":
                field_type = bool
            elif json_type == "array":
                field_type = list[str]  # Wir nehmen an, es ist eine Liste von Strings

            # Ist das Feld Pflicht?
            if field_name in required_fields:
                fields[field_name] = (
                    field_type,
                    Field(description=field_info.get("description", "")),
                )
            else:
                fields[field_name] = (
                    field_type | None,
                    Field(default=None, description=field_info.get("description", "")),
                )

        # Das dynamische Model erzeugen
        ArgsModel = create_model(f"{tool_name}Args", **fields)

        # 2. Die Ausführungsfunktion (Wrapper)
        async def tool_func(**kwargs):
            try:
                # Egal was Mistral halluziniert ('.', URL, leer), wir setzen
                # hier hart den korrekten Pfad, den der MCP Server erwartet.
                if "repo_path" in kwargs:
                    kwargs["repo_path"] = "/app/work_dir"

                # Aufruf an MCP Server
                result = await self.session.call_tool(tool_name, arguments=kwargs)

                output_text = []

                # Prüfen auf Content
                if hasattr(result, "content") and result.content:
                    for content in result.content:
                        if content.type == "text":
                            # Das ist der wichtigste Fall für Git
                            output_text.append(content.text)
                        else:
                            # Fallback für Bilder/Audio, falls Git mal sowas sendet (unwahrscheinlich)
                            # Wir greifen NICHT auf .value zu, um Typ-Fehler zu vermeiden.
                            output_text.append(f"[{content.type} content received]")

                # Prüfen auf Fehler-Flag im Result
                if hasattr(result, "isError") and result.isError:
                    return f"ERROR executing {tool_name}: {', '.join(output_text)}"

                final_output = "\n".join(output_text)

                # WICHTIG: Leere Antworten verhindern (für Mistral)
                # Wenn git_commit erfolgreich ist aber nichts sagt, geben wir "Success" zurück.
                if not final_output.strip():
                    return f"Tool {tool_name} executed successfully (no output)."

                return final_output

            except Exception as e:
                # WICHTIG: Wir fangen Python-Fehler ab und geben sie als String zurück,
                # damit der Agent-Loop nicht bricht (und Mistral eine Antwort bekommt).
                return f"EXCEPTION in tool {tool_name}: {str(e)}"

        # 3. Das finale LangChain Tool zurückgeben
        return StructuredTool.from_function(
            func=None,
            coroutine=tool_func,
            name=tool_name,
            description=tool_desc,
            args_schema=ArgsModel,
        )
