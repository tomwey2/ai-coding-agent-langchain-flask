import os
from contextlib import AsyncExitStack

# LangChain / Pydantic Imports
from langchain_core.tools import StructuredTool

# MCP Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import Field, create_model


# --- GENERISCHE KLASSE ---
class McpServerClient:
    """
    Ein generischer Client, der sich mit EINEM beliebigen MCP-Server verbindet
    und dessen Tools für LangChain bereitstellt.
    """

    def __init__(self, command: str, args: list[str], env: dict):
        """
        :param command: Der Befehl zum Starten (z.B. "uv", "npx", sys.executable)
        :param args: Argumente für den Befehl (z.B. ["mcp-server-git", ...])
        :param env: Umgebungsvariablen (optional)
        """
        self.server_params = StdioServerParameters(
            command=command, args=args, env=env if env else os.environ.copy()
        )
        self.exit_stack = AsyncExitStack()
        self.session = None

    async def __aenter__(self):
        """Startet den Server und die Session."""
        try:
            read, write = await self.exit_stack.enter_async_context(
                stdio_client(self.server_params)
            )
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.session.initialize()
            return self
        except Exception as e:
            # Falls der Server nicht startet, räumen wir auf und werfen den Fehler weiter
            await self.exit_stack.aclose()
            raise RuntimeError(
                f"Failed to start MCP Server ({self.server_params.command}): {e}"
            )

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Räumt auf und stoppt den Server."""
        await self.exit_stack.aclose()

    async def get_langchain_tools(self):
        """Holt Tools vom Server und konvertiert sie."""
        if not self.session:
            raise RuntimeError("MCP Session not started.")

        mcp_tools_list = await self.session.list_tools()
        langchain_tools = []

        for tool_schema in mcp_tools_list.tools:
            lc_tool = self._convert_to_langchain_tool(tool_schema)
            langchain_tools.append(lc_tool)

        return langchain_tools

    async def call_tool(self, tool_name: str, **kwargs):
        """Ruft ein Tool direkt auf und gibt das rohe Ergebnis zurück."""
        if not self.session:
            raise RuntimeError("MCP Session not started.")
        try:
            # Führe den Tool-Aufruf über die MCP-Session aus
            result = await self.session.call_tool(tool_name, arguments=kwargs)

            # Überprüfe auf Fehler
            if result.isError:
                error_message = "Unknown error"
                if result.content and result.content[0].type == "text":
                    error_message = result.content[0].text
                raise RuntimeError(f"Error calling tool '{tool_name}': {error_message}")

            # Extrahiere und gib den Inhalt zurück
            # Wir nehmen hier an, dass der für uns relevante Inhalt im ersten Content-Block ist
            # und ein JSON-Objekt ist, das direkt zurückgegeben werden kann.
            if result.content:
                # Trello und andere Server senden oft JSON-Daten
                if result.content[0].type == "application/json":
                    return result.content[0].json
                # Fallback für reinen Text
                elif result.content[0].type == "text":
                    return result.content[0].text

            return None  # Kein Inhalt

        except Exception as e:
            raise RuntimeError(f"Failed to call tool '{tool_name}': {e}") from e

    def _convert_to_langchain_tool(self, tool_schema):
        """Wandelt MCP Schema in LangChain Tool."""
        tool_name = tool_schema.name
        tool_desc = tool_schema.description or "No description."

        fields = {}
        input_schema = tool_schema.inputSchema or {}
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        for field_name, field_info in properties.items():
            field_type = str
            json_type = field_info.get("type")
            if json_type == "integer":
                field_type = int
            elif json_type == "boolean":
                field_type = bool
            elif json_type == "array":
                field_type = list[str]

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

        ArgsModel = create_model(f"{tool_name}Args", **fields)

        async def tool_func(**kwargs):
            try:
                if not self.session:
                    raise RuntimeError(
                        "MCP Session not connected. Ensure the client is used within an 'async with' block."
                    )

                # Pfad-Injection für Git Server (Spezialfall, könnte man auch auslagern)
                if "repo_path" in kwargs:
                    kwargs["repo_path"] = "/app/work_dir"

                result = await self.session.call_tool(tool_name, arguments=kwargs)

                output_text = []
                if hasattr(result, "content") and result.content:
                    for content in result.content:
                        if content.type == "text":
                            output_text.append(content.text)
                        else:
                            output_text.append(f"[{content.type} content]")

                if hasattr(result, "isError") and result.isError:
                    return f"ERROR executing {tool_name}: {', '.join(output_text)}"

                final = "\n".join(output_text)
                return (
                    final
                    if final.strip()
                    else f"Tool {tool_name} executed successfully."
                )

            except Exception as e:
                return f"EXCEPTION in tool {tool_name}: {str(e)}"

        return StructuredTool.from_function(
            func=None,
            coroutine=tool_func,
            name=tool_name,
            description=tool_desc,
            args_schema=ArgsModel,
        )
