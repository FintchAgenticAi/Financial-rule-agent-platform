from langchain_ollama import ChatOllama


def create_llm() -> ChatOllama:
    return ChatOllama(
        model="llama3.2",
        temperature=0
    )
