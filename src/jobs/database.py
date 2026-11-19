import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_now_plus(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


class JobDatabaseError(RuntimeError):
    pass


class JobRecordNotFound(JobDatabaseError):
    pass


class JobIdConflict(JobDatabaseError):
    pass


class JobStore:
    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = database_path or os.environ.get(
            "JOB_DATABASE_PATH", "data/jobs.db"
        )
        try:
            path = Path(self.database_path).expanduser()
            if not path.is_absolute():
                path = path.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.parent.is_dir():
                raise JobDatabaseError("Job database parent is not a directory.")
            self.database_path = str(path)
        except (OSError, ValueError) as error:
            raise JobDatabaseError(
                "Job database parent directory cannot be created."
            ) from error
        self._local = threading.local()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(
                self.database_path,
                timeout=10,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def _initialize(self) -> None:
        try:
            connection = self._connect()
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_selection_jobs (
                    request_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    r2_bucket TEXT NOT NULL,
                    csv_object_key TEXT NOT NULL,
                    callback_url TEXT NOT NULL,
                    canonical_payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    processing_attempts INTEGER NOT NULL DEFAULT 0,
                    owner_id TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    queued_at TEXT,
                    processing_started_at TEXT,
                    completed_at TEXT,
                    failed_at TEXT,
                    error_message TEXT,
                    transformation_json_key TEXT,
                    validation_json_key TEXT,
                    deduplication_json_key TEXT
                )
                """
            )
            connection.commit()
        except sqlite3.Error as error:
            raise JobDatabaseError("Job database is unavailable.") from error

    def ping(self) -> None:
        try:
            self._connect().execute("SELECT 1").fetchone()
        except sqlite3.Error as error:
            raise JobDatabaseError("Job database is unavailable.") from error

    def submit(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT canonical_payload FROM rule_selection_jobs WHERE request_id = ?",
                (payload["request_id"],),
            ).fetchone()
            if existing is not None:
                if existing["canonical_payload"] != canonical:
                    connection.rollback()
                    raise JobIdConflict("request_id already exists with conflicting data")
                connection.commit()
                record = self.get(payload["request_id"])
                return record, False

            connection.execute(
                """
                INSERT INTO rule_selection_jobs (
                    request_id, batch_id, dataset_id, r2_bucket, csv_object_key,
                    callback_url, canonical_payload, status, processing_attempts,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_enqueue', 0, ?, ?)
                """,
                (
                    payload["request_id"],
                    payload["batch_id"],
                    payload["dataset_id"],
                    payload["r2_bucket"],
                    payload["csv_object_key"],
                    payload["callback_url"],
                    canonical,
                    now,
                    now,
                ),
            )
            connection.commit()
            return self.get(payload["request_id"]), True
        except JobIdConflict:
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise JobDatabaseError("Could not durably persist the job.") from error

    def mark_queued(self, request_id: str) -> None:
        self._update_status(request_id, "queued", queued_at=utc_now())

    def mark_pending_enqueue(self, request_id: str) -> None:
        self._update_status(
            request_id,
            "pending_enqueue",
            owner_id=None,
            lease_expires_at=None,
        )

    def mark_pending_for_owner(
        self,
        request_id: str,
        owner_id: str,
    ) -> bool:
        cursor = self._connect().execute(
            """
            UPDATE rule_selection_jobs
            SET status = 'pending_enqueue',
                owner_id = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE request_id = ? AND status = 'processing' AND owner_id = ?
            """,
            (utc_now(), request_id, owner_id),
        )
        self._connect().commit()
        return cursor.rowcount == 1

    def _update_status(self, request_id: str, status: str, **values: Any) -> None:
        allowed = {
            "queued_at",
            "processing_started_at",
            "completed_at",
            "failed_at",
            "error_message",
            "owner_id",
            "lease_expires_at",
            "transformation_json_key",
            "validation_json_key",
            "deduplication_json_key",
        }
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError(f"Unexpected status fields: {sorted(unexpected)}")
        assignments = ["status = ?", "updated_at = ?"]
        parameters: list[Any] = [status, utc_now()]
        for name, value in values.items():
            assignments.append(f"{name} = ?")
            parameters.append(value)
        parameters.append(request_id)
        try:
            cursor = self._connect().execute(
                f"""
                UPDATE rule_selection_jobs
                SET {", ".join(assignments)}
                WHERE request_id = ?
                """,
                parameters,
            )
            self._connect().commit()
            if cursor.rowcount == 0:
                raise JobRecordNotFound(request_id)
        except sqlite3.Error as error:
            raise JobDatabaseError("Could not update the job.") from error

    def acquire_processing(
        self,
        request_id: str,
        owner_id: str,
        lease_seconds: int,
    ) -> bool:
        now = utc_now()
        expires = utc_now_plus(lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                "SELECT status, owner_id, lease_expires_at, processing_attempts "
                "FROM rule_selection_jobs WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if record is None:
                raise JobRecordNotFound(request_id)

            allowed = record["status"] in {"pending_enqueue", "queued"}
            owner_matches = record["status"] == "processing" and record["owner_id"] == owner_id
            lease_expired = (
                record["status"] == "processing"
                and (
                    record["lease_expires_at"] is None
                    or record["lease_expires_at"] <= now
                )
            )
            if not (allowed or owner_matches or lease_expired):
                connection.commit()
                return False

            attempts = int(record["processing_attempts"]) + 1
            cursor = connection.execute(
                """
                UPDATE rule_selection_jobs
                SET status = 'processing',
                    owner_id = ?,
                    lease_expires_at = ?,
                    processing_attempts = ?,
                    processing_started_at = COALESCE(processing_started_at, ?),
                    updated_at = ?
                WHERE request_id = ?
                """,
                (owner_id, expires, attempts, now, now, request_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        except JobRecordNotFound:
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise JobDatabaseError("Could not acquire job execution ownership.") from error

    def renew_lease(self, request_id: str, owner_id: str, lease_seconds: int) -> bool:
        cursor = self._connect().execute(
            """
            UPDATE rule_selection_jobs
            SET lease_expires_at = ?, updated_at = ?
            WHERE request_id = ? AND status = 'processing' AND owner_id = ?
            """,
            (utc_now_plus(lease_seconds), utc_now(), request_id, owner_id),
        )
        self._connect().commit()
        return cursor.rowcount == 1

    def mark_completed(
        self,
        request_id: str,
        owner_id: str,
        result: dict[str, Any],
    ) -> None:
        cursor = self._connect().execute(
            """
            UPDATE rule_selection_jobs
            SET status = 'completed',
                owner_id = NULL,
                lease_expires_at = NULL,
                completed_at = ?,
                failed_at = NULL,
                error_message = NULL,
                transformation_json_key = ?,
                validation_json_key = ?,
                deduplication_json_key = ?,
                updated_at = ?
            WHERE request_id = ? AND status = 'processing' AND owner_id = ?
            """,
            (
                utc_now(),
                result["transformation_json_key"],
                result["validation_json_key"],
                result["deduplication_json_key"],
                utc_now(),
                request_id,
                owner_id,
            ),
        )
        self._connect().commit()
        if cursor.rowcount == 0:
            raise JobDatabaseError("Execution ownership is no longer valid.")

    def mark_failed(
        self,
        request_id: str,
        owner_id: str,
        error_message: str,
    ) -> None:
        cursor = self._connect().execute(
            """
            UPDATE rule_selection_jobs
            SET status = 'failed',
                owner_id = NULL,
                lease_expires_at = NULL,
                failed_at = ?,
                error_message = ?,
                updated_at = ?
            WHERE request_id = ? AND status = 'processing' AND owner_id = ?
            """,
            (utc_now(), error_message[:500], utc_now(), request_id, owner_id),
        )
        self._connect().commit()
        if cursor.rowcount == 0:
            raise JobDatabaseError("Execution ownership is no longer valid.")

    def get(self, request_id: str) -> dict[str, Any]:
        try:
            row = self._connect().execute(
                "SELECT * FROM rule_selection_jobs WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        except sqlite3.Error as error:
            raise JobDatabaseError("Could not read the job.") from error
        if row is None:
            raise JobRecordNotFound(request_id)
        record = dict(row)
        return record

    def status_payload(self, request_id: str) -> dict[str, Any]:
        record = self.get(request_id)
        return {
            "request_id": record["request_id"],
            "batch_id": record["batch_id"],
            "dataset_id": record["dataset_id"],
            "status": record["status"],
            "processing_attempts": record["processing_attempts"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "queued_at": record["queued_at"],
            "processing_started_at": record["processing_started_at"],
            "completed_at": record["completed_at"],
            "failed_at": record["failed_at"],
            "error_message": record["error_message"],
            "r2_object_keys": {
                "transformation": record["transformation_json_key"],
                "validation": record["validation_json_key"],
                "deduplication": record["deduplication_json_key"],
            },
        }

    def pending_enqueue_ids(self) -> list[str]:
        rows = self._connect().execute(
            "SELECT request_id FROM rule_selection_jobs "
            "WHERE status = 'pending_enqueue' ORDER BY created_at"
        ).fetchall()
        return [row["request_id"] for row in rows]

    def recover_expired_processing(self) -> int:
        now = utc_now()
        cursor = self._connect().execute(
            """
            UPDATE rule_selection_jobs
            SET status = 'pending_enqueue',
                owner_id = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE status = 'processing'
              AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            """,
            (now, now),
        )
        self._connect().commit()
        return cursor.rowcount

