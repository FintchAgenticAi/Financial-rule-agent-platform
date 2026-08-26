# Financial Rule Agent Platform

A Python-based financial data rule selection platform that profiles a CSV dataset, queries rule catalogs from MCP-style clients, and uses a LangGraph workflow with Ollama-based LLM agents to recommend transformation, validation, and deduplication rules.

This project is intentionally focused on rule selection rather than executing transformations. It reads the dataset, inspects column quality, selects rules from existing catalogs, and saves a final JSON package for review.

## What the platform does

The application performs the following steps:

1. Loads a CSV file from a user-specified path or the default sample dataset.
2. Profiles the dataset to extract metadata such as row count, duplicate count, missing values, and sample values per column.
3. Contacts three MCP-style clients for rule catalogs:
   - transformation rules
   - validation rules
   - deduplication rules
4. Runs a LangGraph workflow that selects suitable rules with LLM agents.
5. Writes the final approved-style result to outputs/selected_rules.json.

## Core workflow

The pipeline is defined in src/workflows/graph.py and follows this order:

- profile_dataset
- select_transformations
- select_validations
- select_deduplication
- create_final_result

The graph compiles with StateGraph from LangGraph and stores state in src/state.py.

## Project structure

- src/main.py — entry point for the app
- src/config.py — creates the LLM client and MCP clients
- src/state.py — workflow state schema
- src/workflows/graph.py — LangGraph workflow definition
- src/services/dataset_profiler.py — dataset inspection and metadata generation
- src/services/final_result.py — final JSON output writer
- src/agents/ — LLM-based rule selection agents
- src/mcp_clients/ — Async catalog clients for rule sources
- src/utils/json_tools.py — JSON parsing and rule validation helpers
- rules/ — sample rule catalogs used by the platform
- data/ — sample CSV datasets
- outputs/ — generated final result files

## Rule catalogs

The project includes mock rule sets in the rules folder:

- transformation_rules.json
- validation_rules.json
- deduplication_rules.json

Each catalog contains rules with IDs, descriptions, applicable data types, and parameters. The LLM agent is guided to select only rule IDs that exist in the catalog.

## Setup

1. Create and activate a virtual environment.
2. Install the Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Ensure Ollama is installed and running locally.
4. Make sure the model used by the app is available. The project currently configures:

   ```python
   ChatOllama(model="llama3.2", temperature=0)
   ```

5. Start local services for the MCP rule endpoints if you are using the external catalog pattern. The default environment variables are:

   - TRANSFORMATION_MCP_URL = http://localhost:8001
   - VALIDATION_MCP_URL = http://localhost:8002
   - DEDUPLICATION_MCP_URL = http://localhost:8003

   The app will still initialize with these defaults if the environment variables are not set.

## Running the application

From the project root, run:

```bash
python -m src.main
```

You will be prompted to enter a CSV path. If you leave it empty, the app uses:

```text
data/sample_financial_data.csv
```

## Example output

The workflow generates a final package in outputs/selected_rules.json with structure similar to:

```json
{
  "status": "completed",
  "dataset": "sample_financial_data.csv",
  "dataset_profile": { ... },
  "selected_rules": {
    "transformation": [ ... ],
    "validation": [ ... ],
    "deduplication": [ ... ]
  },
  "execution_status": "not_executed",
  "requires_approval": true
}
```

The app does not modify the dataset itself; it only prepares a rule recommendation package for approval.

## Behavior of the agents

Each selector agent uses the dataset profile and the relevant catalog to return JSON in a controlled structure:

```json
{
  "selected_rules": [
    {
      "rule_id": "TR-001",
      "recommended_columns": ["column_name"],
      "reason": "Why the rule is relevant",
      "confidence": 0.90
    }
  ]
}
```

Before saving the output, the code validates that every selected rule ID exists in the given catalog. This prevents invalid or invented rule IDs from being included.

## Important implementation notes

- The platform current version is a rule recommendation engine, not a data transformation executor.
- It uses mock or MCP-style JSON catalogs rather than direct database integration.
- The selected rules are saved to disk as reviewable output, but the execution_status remains not_executed until a later approval/execution phase is implemented.
- The app handles common CSV issues such as missing files or invalid CSV parsing errors.

## Default sample dataset

The sample financial dataset in data/sample_financial_data.csv contains examples like company names, transaction dates, prices, currencies, and revenue values to test validation and transformation recommendations.

## License

This project is currently intended for educational and prototype use in an industrial project context.
