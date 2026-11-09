from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph

from src.agents.deduplication_selector import make_deduplication_selector
from src.agents.transformation_selector import make_transformation_selector
from src.agents.validation_selector import make_validation_selector
from src.services.dataset_profiler import profile_dataset
from src.services.final_result import create_final_result
from src.state import PlatformState


def build_graph(llm: ChatOllama):
    graph = StateGraph(PlatformState)

    graph.add_node(
        "profile_dataset",
        profile_dataset
    )

    graph.add_node(
        "select_transformations",
        make_transformation_selector(llm)
    )

    graph.add_node(
        "select_validations",
        make_validation_selector(llm)
    )

    graph.add_node(
        "select_deduplication",
        make_deduplication_selector(llm)
    )

    graph.add_node(
        "create_final_result",
        create_final_result
    )

    graph.add_edge(
        START,
        "profile_dataset"
    )

    graph.add_edge(
        "profile_dataset",
        "select_transformations"
    )

    graph.add_edge(
        "select_transformations",
        "select_validations"
    )

    graph.add_edge(
        "select_validations",
        "select_deduplication"
    )

    graph.add_edge(
        "select_deduplication",
        "create_final_result"
    )

    graph.add_edge(
        "create_final_result",
        END
    )

    return graph.compile()
