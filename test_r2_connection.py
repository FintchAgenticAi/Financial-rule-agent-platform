import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.services.r2_service import R2DownloadError, R2Service


def main() -> int:
    load_dotenv()
    try:
        service = R2Service()
        object_key = os.environ["R2_TEST_OBJECT_KEY"]
        destination = Path(os.environ["R2_LOCAL_DOWNLOAD_PATH"])

        print("Connecting to Cloudflare R2...")
        service.head_object(object_key)
        print("R2 object found.")
        print("Downloading CSV...")
        downloaded_path = service.download_csv(
            object_key=object_key,
            destination_path=destination,
            overwrite=True,
        )
        with downloaded_path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file))
        if not rows or not rows[0] or not any(cell.strip() for cell in rows[0]):
            raise R2DownloadError("Downloaded CSV has no nonempty header.")
        print("Download completed successfully.")
        print()
        print(f"Bucket: {os.environ['R2_BUCKET']}")
        print(f"Object key: {object_key}")
        print(f"Filename: {downloaded_path.name}")
        print(f"Local path: {downloaded_path}")
        print(f"Bytes: {downloaded_path.stat().st_size}")
        print("R2 connection test PASSED.")
        return 0
    except (R2DownloadError, ValueError, KeyError) as error:
        print(f"R2 connection test FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
