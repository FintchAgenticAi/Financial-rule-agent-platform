import asyncio
import os
import sys
import traceback
import uuid

from dotenv import load_dotenv

from src.services.rule_processing_service import process_r2_dataset


async def main() -> int:
    load_dotenv()
    request_id = f"dev-{uuid.uuid4().hex[:12]}"
    ollama_base_url = os.environ.get(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
    )
    print(f"ChatOllama base URL: {ollama_base_url}")

    try:
        result = await process_r2_dataset(
            request_id=request_id,
            dataset_id="ds-001",
            r2_bucket=os.environ["R2_BUCKET"],
            csv_object_key=os.environ["R2_TEST_OBJECT_KEY"],
        )
    except Exception as error:
        print(f"R2 full workflow FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    print("R2 full workflow PASSED")
    print(f"Request ID: {result['request_id']}")
    print(f"Dataset ID: {result['dataset_id']}")
    print(f"Bucket: {result['r2_bucket']}")
    print(f"Transformation JSON key: {result['transformation_json_key']}")
    print(f"Validation JSON key: {result['validation_json_key']}")
    print(f"Deduplication JSON key: {result['deduplication_json_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
