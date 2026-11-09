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
5. Writes selected transformation, validation, and deduplication rules to separate JSON files in the outputs folder.

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

5. Make the MCP rule services available before starting the application. The default endpoints are:

  - TRANSFORMATION_MCP_URL = http://10.23.1.35:8010/mcp
  - VALIDATION_MCP_URL = http://VALIDATION_SERVER_IP:8030/mcp
  - DEDUPLICATION_MCP_URL = http://DEDUPLICATION_SERVER_IP:8000/mcp

  The transformation service is configured in the current code as `10.23.1.35:8010`. Replace the validation and deduplication placeholders with the actual remote server addresses. Set the environment variables before running if these locations differ.

## Running the application

From the project root, run:

```bash
python -m src.main
```

The application then:

1. Requests each rule catalog from its MCP endpoint. If an endpoint is unavailable, it uses the matching file in `rules/`.
2. Reads and profiles the selected CSV file.
3. Sends the profile and catalogs to the local Ollama `llama3.2` model through the three selector agents.
4. Writes the selected rules to the three JSON files in `outputs/`.

The computer running this project is the client/orchestrator. It reads the CSV, calls the MCP services, runs Ollama and the LangGraph workflow, and writes the output files. The computer at `10.23.1.35` only provides the transformation catalog endpoint; it must be reachable over the network, and its firewall must allow port `8010`.

You will be prompted to enter a CSV path. If you leave it empty, the app uses:

```text
data/sample_financial_data.csv
```

## Cloudflare R2 Connection Test

The standalone R2 test downloads one CSV from Cloudflare R2 into `data/`. It does
not start Ollama, contact MCP services, or run the LangGraph workflow.

1. Activate the existing virtual environment in Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   Install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Replace the R2 placeholders in the project-root `.env` with the Cloudflare
   R2 endpoint, access key, and secret key. Keep the existing Ollama and MCP
   settings unchanged. The default bucket is
   `financial-rule-platform-dev`.

3. Manually upload a readable CSV to that R2 bucket using the Cloudflare
   dashboard or an S3-compatible client. The uploaded object key must exactly
   match `R2_TEST_OBJECT_KEY` (by default,
   `datasets/ds-001/sample_financial_data.csv`). Do not use a normal AWS S3 endpoint.

4. Run the independent connection test:

   ```powershell
   python test_r2_connection.py
   ```

   A successful run reports the bucket, object key, local filename, byte count,
   and `R2 connection test PASSED.` The file appears at
   `data/r2_test_input.csv` by default.

Common failures indicate either placeholder or missing environment variables,
an incorrect HTTPS R2 endpoint, a missing object key, or insufficient bucket
permissions. Check that the key matches exactly and that the R2 token permits
object read and head operations for the configured bucket. Credentials are
never printed by the test.

## Example output

The workflow generates three files in the outputs folder:

- `selected_transformation_rules.json`
- `selected_validation_rules.json`
- `selected_deduplication_rules.json`

Each file contains the selected rules for one category, for example:

```json
[
  {
    "rule": { ... },
    "recommended_columns": ["column_name"],
    "reason": "Why the rule is relevant",
    "confidence": 0.90
  }
]
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
- The selected rules are saved to separate files as reviewable output, but they are not executed against the dataset.
- The app handles common CSV issues such as missing files or invalid CSV parsing errors.

## Default sample dataset

The sample financial dataset in data/sample_financial_data.csv contains examples like company names, transaction dates, prices, currencies, and revenue values to test validation and transformation recommendations.

## Docker Deployment

The Docker image packages the Python application and the fallback rule catalogs. Ollama and all MCP servers remain external services; they are not installed or started by the image. The container runs the existing interactive CLI entry point:

```text
python -m src.main
```

The container is not an HTTP API and does not expose a port.

### Prerequisites

Install the following on the computer that will run the container:

- Docker Desktop with the Linux container engine enabled.
- Git, if cloning the repository.
- Ollama running on the Docker host.
- Network access from Docker Desktop to the Ollama host and the three remote MCP laptops.
- The repository's `data/` and `outputs/` directories.

The Dockerfile uses the official `python:3.14-slim` image. It installs the pinned dependencies in `requirements.txt`, runs as the non-root `appuser` (UID `10001`), and starts the CLI with `python -m src.main`.

### Install Docker Desktop on Windows

1. Download Docker Desktop from [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Install it with the recommended WSL 2 backend.
3. Start Docker Desktop and wait until the engine reports that it is running.
4. Verify the installation in PowerShell:

   ```powershell
   docker --version
   docker compose version
   ```

5. If Docker Desktop asks for file-sharing permission, allow access to the drive containing this repository. Compose bind mounts require access to `data/`, `outputs/`, and, for development, `src/` and `rules/`.

### Install and prepare Ollama

Install Ollama on the same Windows laptop that runs Docker Desktop. Pull the configured model and verify it locally:

```powershell
ollama pull llama3.2
ollama list
```

The container reaches host Ollama through:

```text
http://host.docker.internal:11434
```

This value is configured in `.env` as `OLLAMA_BASE_URL`. `host.docker.internal` is required because `localhost` inside a container refers to the container itself, not the Windows host.

### Configure the external MCP servers

The application has three independent HTTP MCP clients. Each configured base URL receives `/rules` from the client, so a configured URL such as `http://server:8010/mcp` is requested as `http://server:8010/mcp/rules`.

Copy the example environment file and edit the remote addresses:

```powershell
Copy-Item .env.example .env
notepad .env
```

The current `.env.example` contains:

```dotenv
OLLAMA_MODEL=llama3.2
OLLAMA_BASE_URL=http://host.docker.internal:11434

TRANSFORMATION_MCP_URL=http://10.23.1.35:8010/mcp
VALIDATION_MCP_URL=http://VALIDATION_SERVER_IP:8030/mcp
DEDUPLICATION_MCP_URL=http://DEDUPLICATION_SERVER_IP:8000/mcp
```

Replace `VALIDATION_SERVER_IP` and `DEDUPLICATION_SERVER_IP` with the actual IP addresses or DNS names of those remote laptops. Do not leave placeholder values for a remote-MCP-backed run. The transformation address is the known configured endpoint and may also need to be changed if its laptop address changes. Ensure each remote server is listening on its configured port and that its firewall allows requests from the Docker Desktop network.

The `.env` file is intentionally local-only. It is excluded by `.gitignore` and `.dockerignore`; do not commit it or put credentials in the image. If an MCP server later requires authentication, provide credentials through a secret-management mechanism rather than committing them to this repository.

### Build the image

From the repository root, build the local versioned image:

```powershell
docker build -t financial-rule-agent:1.0.0 .
```

The build context includes `src/` and `rules/`. The `.dockerignore` excludes local virtual environments, `.env`, `data/`, `outputs/`, logs, caches, Git metadata, and editor files. Therefore, input datasets and generated results are supplied at runtime rather than embedded in the image.

### Run with Docker Compose

The base [`compose.yaml`](compose.yaml) loads `.env`, keeps the CLI interactive, and mounts:

```text
./data    -> /app/data       read-only
./outputs -> /app/outputs    read-write
```

Validate the configuration:

```powershell
docker compose -f compose.yaml config --quiet
```

Build and run the application:

```powershell
docker compose -f compose.yaml build
docker compose -f compose.yaml run --rm financial-rule-agent
```

When prompted, enter a path inside the container. For a dataset in the host `data/` directory, use:

```text
/app/data/your_dataset.csv
```

Press Enter without a path to use the application's default relative path. For the Compose data mount, the reliable container path is `/app/data/sample_financial_data.csv`.

The application writes these files to the host `outputs/` directory:

```text
dataset_profile.json
selected_transformation_rules.json
selected_validation_rules.json
selected_deduplication_rules.json
```

Do not run the full workflow until all three MCP endpoints have been confirmed. If an endpoint is unavailable, the application reports the failure and uses its matching catalog in `rules/`. This fallback is useful for testing but may use stale catalogs in production.

### Development Compose mode

Use the development override when editing in VS Code:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker compose -f compose.yaml -f compose.dev.yaml run --rm financial-rule-agent
```

The [`compose.dev.yaml`](compose.dev.yaml) override adds read-only live bind mounts:

```text
./src   -> /app/src      read-only
./rules -> /app/rules    read-only
```

Changes saved in VS Code are visible to the next container run without rebuilding. This is still the same interactive CLI; Compose does not add a web server, daemon, or hot-reload process. Use only `compose.yaml` for a production-style image test without development source and rule mounts.

### Safe validation and testing

Check the image metadata and entry point:

```powershell
docker image inspect financial-rule-agent:1.0.0 `
  --format 'User={{.Config.User}} WorkDir={{.Config.WorkingDir}} Cmd={{json .Config.Cmd}}'
```

The expected values are `appuser`, `/app`, and `["python","-m","src.main"]`.

Verify imports without starting the interactive workflow:

```powershell
docker run --rm --entrypoint python financial-rule-agent:1.0.0 -c `
  "import httpx, langchain_ollama, langgraph, pandas, pydantic; print('imports: OK')"
```

Test Docker-to-host Ollama connectivity:

```powershell
docker run --rm --entrypoint python financial-rule-agent:1.0.0 -c `
  "import httpx; r=httpx.get('http://host.docker.internal:11434/api/tags', timeout=5); print(r.status_code); r.raise_for_status()"
```

For a workflow test, use a synthetic CSV mounted from a temporary host directory and mount a separate temporary output directory. Enter its container path, such as `/app/data/synthetic.csv`. This avoids modifying production datasets or repository outputs. Confirm that all five workflow stages complete and that the four JSON files appear in the temporary output directory.

### Docker Hub publishing

The private image repository is:

```text
sunaliperera/financial-rule-agent
```

Log in, tag the local image, and push the immutable `1.0.0` version:

```powershell
docker login
docker tag financial-rule-agent:1.0.0 sunaliperera/financial-rule-agent:1.0.0
docker push sunaliperera/financial-rule-agent:1.0.0
```

Do not overwrite a published version tag. If a moving `latest` tag is intentionally maintained, create and push it separately:

```powershell
docker tag financial-rule-agent:1.0.0 sunaliperera/financial-rule-agent:latest
docker push sunaliperera/financial-rule-agent:latest
```

### Pull and run on another computer

On another computer with Docker Desktop:

```powershell
docker login
docker pull sunaliperera/financial-rule-agent:1.0.0
docker tag sunaliperera/financial-rule-agent:1.0.0 financial-rule-agent:1.0.0
```

Clone or copy the repository files needed for runtime configuration, create `.env` from `.env.example`, and provide local `data/` and `outputs/` directories. The existing Compose file refers to the local image name `financial-rule-agent:1.0.0`, so the local tag command above lets it run without rebuilding:

```powershell
docker compose -f compose.yaml run --rm financial-rule-agent
```

Alternatively, run the image directly while preserving the CLI and volumes:

```powershell
docker run --rm -it `
  --env-file .env `
  -v "${PWD}\data:/app/data:ro" `
  -v "${PWD}\outputs:/app/outputs" `
  financial-rule-agent:1.0.0
```

On Linux or macOS, use the corresponding host path syntax. Ollama must be reachable at the configured `OLLAMA_BASE_URL`; Docker Desktop provides `host.docker.internal` on Windows and macOS, while Linux users may need to set a reachable host address instead.

### Runtime volume and permission notes

The image creates `/app/data` and `/app/outputs` and runs as `appuser` UID `10001`. Docker Desktop normally permits the bind mounts above, but the host directories must exist and be shared with Docker Desktop. The data mount is read-only so the application cannot modify input CSV files. The outputs mount must be writable because profiling and final rule files are created there.

If output writes fail on Windows, confirm Docker Desktop file sharing, verify that `outputs/` exists, and check the resolved mount configuration:

```powershell
docker compose -f compose.yaml config
```

### Security considerations

- Never commit `.env`, real financial datasets, generated customer-specific outputs, or credentials.
- Use `.env.example` only for non-secret variable names and safe placeholders.
- Review the dataset profile before sharing it: the profile includes column names and sample values.
- The selector agents receive the dataset profile and catalog contents through Ollama. Keep Ollama and all MCP traffic on trusted networks, and use HTTPS/authentication when the external services support it.
- The current MCP clients use HTTP and do not implement authentication. Do not expose the MCP servers publicly without appropriate network controls.
- The image runs as non-root and does not install Ollama or the external MCP servers.
- Keep `data/` read-only in Compose and use a separate writable `outputs/` directory.
- Pin and review dependency changes in `requirements.txt` before rebuilding or publishing.

### Troubleshooting

**`docker: command not found` or the Docker engine is unavailable**

Start Docker Desktop, wait for the engine to become ready, and rerun `docker --version` and `docker compose version`.

**Ollama connection refused or timed out**

Confirm Ollama is running and that `llama3.2` is installed:

```powershell
ollama list
ollama run llama3.2
```

Inside Docker, use `http://host.docker.internal:11434`, not `http://localhost:11434`. Check Windows firewall rules if the connectivity test cannot reach `/api/tags`.

**MCP connection failure**

Check each `*_MCP_URL` in `.env`, confirm the remote laptop IP and port, verify the server's `/mcp/rules` endpoint, and allow inbound traffic through the remote laptop firewall. The application may continue with local fallback catalogs; confirm that this behavior is acceptable before treating the run as successful.

**`Dataset not found`**

The path is resolved inside the container. Use `/app/data/<filename>` for a file in the host `data/` directory, and confirm the file is not excluded from a custom runtime mount.

**Cannot write output files**

Ensure the host `outputs/` directory exists, is writable, and is shared with Docker Desktop. Do not mount it read-only.

**Changes in VS Code are not visible**

Use both Compose files:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml run --rm financial-rule-agent
```

The development mounts are not active when only `compose.yaml` is used.

## License

This project is currently intended for educational and prototype use in an industrial project context.
