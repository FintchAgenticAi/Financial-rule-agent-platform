import os
from typing import Dict

from langchain_ollama import ChatOllama

from src.mcp_clients.transformation import TransformationMCPClient
from src.mcp_clients.validation import ValidationMCPClient
from src.mcp_clients.deduplication import DeduplicationMCPClient


def create_llm() -> ChatOllama:
    return ChatOllama(
        model="llama3.2",
        temperature=0
    )


def create_mcp_clients() -> Dict[str, object]:
    transform_url = os.environ.get("TRANSFORMATION_MCP_URL", "http://localhost:8001")
    validate_url = os.environ.get("VALIDATION_MCP_URL", "http://localhost:8002")
    dedup_url = os.environ.get("DEDUPLICATION_MCP_URL", "http://localhost:8003")

    return {
        "transformation": TransformationMCPClient(transform_url, "transformation"),
        "validation": ValidationMCPClient(validate_url, "validation"),
        "deduplication": DeduplicationMCPClient(dedup_url, "deduplication"),
    }
