from typing import Any, TypedDict


class PlatformState(TypedDict, total=False):
    dataset_path: str
    dataset_profile: dict[str, Any]

    transformation_catalog: list[dict[str, Any]]
    validation_catalog: list[dict[str, Any]]
    deduplication_catalog: list[dict[str, Any]]

    selected_transformations: list[dict[str, Any]]
    selected_validations: list[dict[str, Any]]
    selected_deduplications: list[dict[str, Any]]

    final_result: dict[str, Any]
