"""Shared LLM configuration for all LangGraph agents."""
import os
from langchain_openai import ChatOpenAI


def get_llm() -> ChatOpenAI:
    """Get the configured LLM instance using environment variables."""
    return ChatOpenAI(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("MODEL_ID", "sonnet"),
        temperature=0.3,
        max_tokens=2000,
    )
