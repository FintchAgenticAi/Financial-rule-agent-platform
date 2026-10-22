import os
from typing import Dict

from langchain_ollama import ChatOllama

from src.mcp_clients.transformation import TransformationMCPClient
from src.mcp_clients.validation import ValidationMCPClient
from src.mcp_clients.deduplication import DeduplicationMCPClient


def create_llm() -> ChatOllama:
    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
        base_url=os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        ),
        temperature=0
    )


def create_mcp_clients() -> Dict[str, object]:
    transform_url = os.environ.get(
        "TRANSFORMATION_MCP_URL", "http://10.23.1.35:8010/mcp"
    )
    validate_url = os.environ.get(
        "VALIDATION_MCP_URL", "http://VALIDATION_SERVER_IP:8030/mcp"
    )
    dedup_url = os.environ.get(
        "DEDUPLICATION_MCP_URL", "http://DEDUPLICATION_SERVER_IP:8000/mcp"
    )

    return {
        "transformation": TransformationMCPClient(transform_url, "transformation"),
        "validation": ValidationMCPClient(validate_url, "validation"),
        "deduplication": DeduplicationMCPClient(dedup_url, "deduplication"),
    }
