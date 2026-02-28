import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv

try:
    from langgraph.prebuilt import create_react_agent
except ImportError:
    create_react_agent = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

load_dotenv()


def get_chat_model() -> "ChatOpenAI":
    """Initialize and return a ChatOpenAI model from environment settings.
    
    Requires BASE_URL and OPENAI_API_KEY environment variables.
    MODEL_NAME is optional (defaults to provider default).
    """
    if ChatOpenAI is None:
        raise ImportError("langchain-openai is required: pip install langchain-openai")
    base_url = os.environ.get("BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        raise EnvironmentError(
            "BASE_URL and OPENAI_API_KEY environment variables are required for LLM tests"
        )
    return ChatOpenAI(
        model=os.environ.get("MODEL_NAME"),
        base_url=base_url,
        api_key=api_key,
        temperature=0.7,
    )


async def run_e2e_test_with_client(client: MultiServerMCPClient, expected_tools: list[str], test_prompts: list[tuple[str, str]]) -> None:
    """Run an end-to-end test using a connected MCP client and validate tool behavior."""
    tools = await client.get_tools()
    tool_names = [tool.name for tool in tools]
    print(f"🔧 Tools list: {tool_names}")

    for tool in expected_tools:
        assert tool in tool_names, f"Expected '{tool}' tool to be available"

    # LLM agent invocation is optional — skip if dependencies or env vars missing
    if create_react_agent is None:
        print("⚠️ langgraph not installed, skipping LLM agent tests")
        return

    try:
        model = get_chat_model()
    except (EnvironmentError, ImportError) as e:
        print(f"⚠️ Skipping LLM agent tests: {e}")
        return

    agent = create_react_agent(model, tools)

    for question, expected_answer in test_prompts:
        response = await agent.ainvoke({"messages": question})
        for m in response['messages']:
            m.pretty_print()
        assert any(expected_answer.lower() in m.content.lower() for m in response["messages"]), \
            f"Expected answer to include '{expected_answer}'"
