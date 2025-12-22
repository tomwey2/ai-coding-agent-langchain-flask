import logging

from langchain.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from agent.state import AgentState
from agent.utils import sanitize_response

logger = logging.getLogger(__name__)

# --- OPTIMIERTER PROMPT ---
ANALYST_SYSTEM_PROMPT = """You are a Senior Technical Analyst (Read-Only).
Your goal: Analyze the codebase to answer the specific question found in the TASK TITLE and DESCRIPTION.

TOOLS ALLOWED: list_files, read_file, log_thought, finish_task.
FORBIDDEN TOOLS: write_to_file, git_add, git_commit, git_push_origin.

ANALYSIS GUIDELINES:
1. UNDERSTAND: First, identify exactly what the user wants to know from the task description.
2. LOCATE: Find the relevant files using 'list_files'.
3. EXAMINE: Read the content of those files using 'read_file'.
4. SYNTHESIZE: Combine your findings. Quote code parts if necessary to prove your point.
5. NO CHANGES: You must NOT modify any code.

WORKFLOW:
1. [ ] Explore file structure (list_files).
2. [ ] Read specific relevant files (read_file).
3. [ ] Analyze findings (log_thought).
4. [ ] REPORT: Call 'finish_task' with the comprehensive analysis as the summary.
"""


def create_analyst_node(llm: BaseChatModel, tools, repo_url):
    async def analyst_node(state: AgentState):
        # Prompt mit Repo-URL anreichern
        sys_msg = f"{ANALYST_SYSTEM_PROMPT}\nRepo: {repo_url}\n\nREMINDER: Use 'log_thought' to plan. Use 'finish_task' to report your findings."
        current_messages = [SystemMessage(content=sys_msg)] + state["messages"]

        # Wir erlauben dem Analysten etwas mehr Freiheit ("auto"), da er oft chatten muss,
        # um zu denken. Aber am Ende soll er finish_task nutzen.
        chain = llm.bind_tools(tools, tool_choice="auto")

        response = await chain.ainvoke(current_messages)
        response = sanitize_response(response)
        logger.info(
            f"\n=== ANALYST RESPONSE ===\nContent: '{response.content}'\nTool Calls: {response.tool_calls}\n============================"
        )

        return {"messages": [response]}

    return analyst_node
