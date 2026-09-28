import os
from typing import Dict

from langchain_ollama import ChatOllama

from src.mcp_clients.transformation import TransformationMCPClient
from src.mcp_clients.validation import ValidationMCPClient
from src.mcp_clients.deduplication import DeduplicationMCPClient
from src.strategies.llm import (
    LLMContext,
    LLMStrategy,
    Llama32Strategy,
    Qwen35Strategy,
)


def get_llm_strategies() -> Dict[str, LLMStrategy]:
    """Return the local LLM strategies available to the application."""
    strategies = [
        Llama32Strategy(),
        Qwen35Strategy(),
    ]
    return {strategy.key: strategy for strategy in strategies}


def create_llm(strategy: LLMStrategy | None = None) -> ChatOllama:
    """Create an LLM through the selected strategy, defaulting to Llama 3.2."""
    context = LLMContext(strategy or Llama32Strategy())
    return context.create_llm()


def create_mcp_clients() -> Dict[str, object]:
    transform_url = os.environ.get("TRANSFORMATION_MCP_URL", "http://localhost:8001")
    validate_url = os.environ.get("VALIDATION_MCP_URL", "http://localhost:8002")
    dedup_url = os.environ.get("DEDUPLICATION_MCP_URL", "http://localhost:8003")

    return {
        "transformation": TransformationMCPClient(transform_url, "transformation"),
        "validation": ValidationMCPClient(validate_url, "validation"),
        "deduplication": DeduplicationMCPClient(dedup_url, "deduplication"),
    }
