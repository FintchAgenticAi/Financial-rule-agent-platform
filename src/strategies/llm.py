from abc import ABC, abstractmethod

from langchain_ollama import ChatOllama


class LLMStrategy(ABC):
    """Common interface for creating a local LLM client."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Return the value used to identify this strategy."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Return the name shown to the user."""

    @abstractmethod
    def create_llm(self) -> ChatOllama:
        """Create the configured local LLM client."""


class Llama32Strategy(LLMStrategy):
    @property
    def key(self) -> str:
        return "llama3.2"

    @property
    def display_name(self) -> str:
        return "Llama 3.2"

    def create_llm(self) -> ChatOllama:
        return ChatOllama(model=self.key, temperature=0)


class Qwen35Strategy(LLMStrategy):
    @property
    def key(self) -> str:
        return "qwen3.5:4b"

    @property
    def display_name(self) -> str:
        return "Qwen 3.5 (4B)"

    def create_llm(self) -> ChatOllama:
        return ChatOllama(model=self.key, temperature=0)


class LLMContext:
    """Delegates LLM creation to the currently selected strategy."""

    def __init__(self, strategy: LLMStrategy):
        self._strategy = strategy

    @property
    def strategy(self) -> LLMStrategy:
        return self._strategy

    def set_strategy(self, strategy: LLMStrategy) -> None:
        self._strategy = strategy

    def create_llm(self) -> ChatOllama:
        return self._strategy.create_llm()