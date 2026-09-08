from pathlib import Path
from typing import Any

import pandas as pd

from src.state import PlatformState


def profile_dataset(state: PlatformState) -> PlatformState:
    dataset_path = Path(state["dataset_path"])

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {dataset_path}"
        )

    if dataset_path.suffix.lower() != ".csv":
        raise ValueError(
            "The basic version supports CSV files only."
        )

    dataframe = pd.read_csv(dataset_path)

    column_profiles: list[dict[str, Any]] = []

    for column in dataframe.columns:
        series = dataframe[column]

        column_profiles.append(
            {
                "column_name": column,
                "pandas_type": str(series.dtype),
                "missing_count": int(
                    series.isna().sum()
                ),
                "unique_count": int(
                    series.nunique(dropna=True)
                ),
                "sample_values": [
                    str(value)
                    for value in series.dropna().head(5).tolist()
                ]
            }
        )

    profile = {
        "file_name": dataset_path.name,
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "duplicate_row_count": int(
            dataframe.duplicated().sum()
        ),
        "columns": column_profiles
    }

    print("[1/5] Dataset profiling completed.")

    return {
        "dataset_profile": profile
    }
