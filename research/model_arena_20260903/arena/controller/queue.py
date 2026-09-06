"""Campaign queue: sqlite (WAL) at ``queue/campaign.sqlite``.

The one invariant that saves the most money (masterplan section 9.3):

    a job that is SUCCESS and carries a raw_output_sha256 is never re-enqueued,
    never reset and never re-dispatched.

Resume is simply re-opening the same database. There is no in-memory campaign
state that a crash could lose.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from arena.constants import CONTROLLER_STATES, ERROR_CLASSES, WORKER_STATES
from arena.provider.safety import utc_now_iso

__all__ = [
    "JOB_STATES",
    "TERMINAL_JOB_STATES",
    "CampaignQueue",
    "JobRecord",
    "PodRecord",
    "QueueError",
    "ShardRecord",
    "WorkerRecord",
]

JOB_STATES: Final = (
    "PENDING",
    "ASSIGNED",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "QUARANTINED",
    "PAUSED",
)
TERMINAL_JOB_STATES: Final = frozenset({"SUCCESS", "QUARANTINED"})
JOB_KINDS: Final = ("inference", "canary", "recovery")
SHARD_STATES: Final = ("PENDING", "RESERVED", "RUNNING", "DONE", "FAILED")

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS jobs (
    inference_job_id  TEXT PRIMARY KEY,
    model_key         TEXT NOT NULL,
    benchmark         TEXT NOT NULL,
    sample_id         TEXT NOT NULL,
    case_key          TEXT NOT NULL,
    shard_id          TEXT NOT NULL,
    job_kind          TEXT NOT NULL,
    state             TEXT NOT NULL,
    attempt           INTEGER NOT NULL DEFAULT 0,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    error_class       TEXT,
    error_message     TEXT,
    worker_id         TEXT,
    receipt_sha256    TEXT,
    raw_output_sha256 TEXT,
    queued_at         TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_by_model_state ON jobs (model_key, state);
CREATE INDEX IF NOT EXISTS jobs_by_shard ON jobs (shard_id, state);

CREATE TABLE IF NOT EXISTS shards (
    shard_id          TEXT PRIMARY KEY,
    model_key         TEXT NOT NULL,
    benchmark         TEXT NOT NULL,
    shard_index       INTEGER NOT NULL,
    job_count         INTEGER NOT NULL,
    predicted_seconds REAL NOT NULL,
    state             TEXT NOT NULL,
    worker_id         TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id         TEXT PRIMARY KEY,
    model_key         TEXT NOT NULL,
    pod_id            TEXT NOT NULL,
    replica_index     INTEGER NOT NULL,
    concurrency       INTEGER NOT NULL,
    state             TEXT NOT NULL,
    jobs_done         INTEGER NOT NULL DEFAULT 0,
    jobs_failed       INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pods (
    pod_id                    TEXT PRIMARY KEY,
    worker_id                 TEXT,
    model_key                 TEXT NOT NULL,
    name                      TEXT NOT NULL,
    gpu_type                  TEXT,
    cloud_type                TEXT,
    data_center_id            TEXT,
    runtime_mode              TEXT,
    listed_rate_usd_per_hour  REAL,
    gpu_count                 INTEGER NOT NULL DEFAULT 1,
    price_snapshot_sha256     TEXT,
    provider_api_version      TEXT,
    authorization_receipt_path    TEXT,
    authorization_receipt_sha256  TEXT,
    provisioned_at            TEXT,
    model_ready_at            TEXT,
    last_job_finished_at      TEXT,
    terminated_at             TEXT,
    state                     TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id        TEXT NOT NULL,
    ts               TEXT NOT NULL,
    state            TEXT NOT NULL,
    job_id           TEXT,
    last_progress_at TEXT,
    gpu_util         REAL,
    vram_used_mb     INTEGER,
    output_progress  INTEGER
);
CREATE INDEX IF NOT EXISTS heartbeats_by_worker ON heartbeats (worker_id, ts);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    from_state  TEXT,
    to_state    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS models (
    model_key         TEXT PRIMARY KEY,
    state             TEXT NOT NULL,
    canary_status     TEXT NOT NULL,
    full_run_eligible INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class QueueError(RuntimeError):
    """The queue refused an operation that would break an invariant."""


@dataclass(frozen=True, slots=True)
class JobRecord:
    inference_job_id: str
    model_key: str
    benchmark: str
    sample_id: str
    case_key: str
    shard_id: str
    job_kind: str
    state: str = "PENDING"
    attempt: int = 0
    retry_count: int = 0
    error_class: str | None = None
    error_message: str | None = None
    worker_id: str | None = None
    receipt_sha256: str | None = None
    raw_output_sha256: str | None = None
    queued_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if self.job_kind not in JOB_KINDS:
            raise QueueError(f"job_kind must be one of {JOB_KINDS}")
        if self.state not in JOB_STATES:
            raise QueueError(f"job state must be one of {JOB_STATES}")
        if self.error_class is not None and self.error_class not in ERROR_CLASSES:
            raise QueueError(f"error_class {self.error_class!r} is outside the taxonomy")


@dataclass(frozen=True, slots=True)
class ShardRecord:
    shard_id: str
    model_key: str
    benchmark: str
    shard_index: int
    job_count: int
    predicted_seconds: float
    state: str = "PENDING"
    worker_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerRecord:
    worker_id: str
    model_key: str
    pod_id: str
    replica_index: int
    concurrency: int
    state: str = "PROVISIONING"
    jobs_done: int = 0
    jobs_failed: int = 0
    last_heartbeat_at: str | None = None


@dataclass(frozen=True, slots=True)
class PodRecord:
    pod_id: str
    model_key: str
    name: str
    state: str
    worker_id: str | None = None
    gpu_type: str | None = None
    cloud_type: str | None = None
    data_center_id: str | None = None
    runtime_mode: str | None = None
    listed_rate_usd_per_hour: float | None = None
    # D57: how many GPUs this pod was provisioned with. listed_rate_usd_per_hour
    # is always the *per-GPU* rate, so cost = seconds/3600 * rate * gpu_count.
    # Defaults to 1 -- a pod row from before this field existed meant one GPU.
    gpu_count: int = 1
    price_snapshot_sha256: str | None = None
    # ARENA_CONTRACT section 11 D2/D6: which API created this pod, and which
    # founder receipt paid for it.
    provider_api_version: str | None = None
    authorization_receipt_path: str | None = None
    authorization_receipt_sha256: str | None = None
    provisioned_at: str | None = None
    model_ready_at: str | None = None
    last_job_finished_at: str | None = None
    terminated_at: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gpu_count < 1:
            raise QueueError("gpu_count must be at least 1")


class CampaignQueue:
    """The controller's durable state. Open it, use it, close it."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        # D76: several drivers hold this file at once, one per shard
        # slice. Without a busy timeout sqlite3 raises "database is
        # locked" the first time two of them write in the same instant;
        # with one they wait, which is what WAL is for.
        self._connection.execute("PRAGMA busy_timeout=300000")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(_SCHEMA)
        self._add_missing_columns()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    # ---------------------------------------------------------------- jobs

    def enqueue(self, jobs: Iterable[JobRecord]) -> tuple[int, int]:
        """Insert jobs, skipping ids that already exist. Returns (added, skipped).

        The skip is decided by the insert itself, not by a read before it
        (D80). Several drivers plan the same model at the same time -- one per
        shard slice -- and "does this id exist?" followed by an insert is a
        race both of them lose: each reads absent, each inserts, and the second
        dies on jobs.inference_job_id. ``ON CONFLICT DO NOTHING`` makes the
        answer and the write one statement, and it never overwrites a row, so
        section 9.3's settled jobs stay settled.

        The whole batch is one ``BEGIN IMMEDIATE`` transaction. The connection
        is in autocommit, so each of the 5,132 inserts used to take and release
        the write lock on its own; nine drivers doing that at once spent longer
        queueing than writing, and a driver that could not get the lock in time
        failed the run instead of waiting for it.
        """

        added = 0
        total = 0
        now = utc_now_iso()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            for job in jobs:
                total += 1
                cursor = self._connection.execute(
                    """
                    INSERT INTO jobs (
                        inference_job_id, model_key, benchmark, sample_id, case_key,
                        shard_id, job_kind, state, attempt, retry_count, error_class,
                        error_message, worker_id, receipt_sha256, raw_output_sha256,
                        queued_at, started_at, finished_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(inference_job_id) DO NOTHING
                    """,
                    (
                        job.inference_job_id,
                        job.model_key,
                        job.benchmark,
                        job.sample_id,
                        job.case_key,
                        job.shard_id,
                        job.job_kind,
                        job.state,
                        job.attempt,
                        job.retry_count,
                        job.error_class,
                        job.error_message,
                        job.worker_id,
                        job.receipt_sha256,
                        job.raw_output_sha256,
                        job.queued_at or now,
                        job.started_at,
                        job.finished_at,
                        now,
                    ),
                )
                if cursor.rowcount > 0:
                    added += 1
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")
        return added, total - added

    def get_job(self, inference_job_id: str) -> JobRecord | None:
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE inference_job_id = ?", (inference_job_id,)
        ).fetchone()
        return None if row is None else _job_from_row(row)

    def jobs_for_model(self, model_key: str, *, state: str | None = None) -> tuple[JobRecord, ...]:
        if state is not None and state not in JOB_STATES:
            raise QueueError(f"unknown job state {state!r}")
        if state is None:
            rows = self._connection.execute(
                "SELECT * FROM jobs WHERE model_key = ? ORDER BY case_key", (model_key,)
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM jobs WHERE model_key = ? AND state = ? ORDER BY case_key",
                (model_key, state),
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def pending_jobs(
        self, *, model_key: str | None = None, shard_id: str | None = None, limit: int = 100
    ) -> tuple[JobRecord, ...]:
        """Jobs eligible for dispatch.

        Only PENDING. A job that is still FAILED has already had every retry
        its section 15.9 rule allows -- the retry path returns a job to PENDING
        explicitly -- so selecting FAILED here would re-run a deterministic
        failure forever, which is the single most expensive pattern the
        masterplan names.
        """

        clauses = ["state = 'PENDING'"]
        params: list[object] = []
        if model_key is not None:
            clauses.append("model_key = ?")
            params.append(model_key)
        if shard_id is not None:
            clauses.append("shard_id = ?")
            params.append(shard_id)
        params.append(limit)
        rows = self._connection.execute(
            f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY case_key LIMIT ?",  # noqa: S608
            tuple(params),
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def mark_running(self, inference_job_id: str, worker_id: str) -> None:
        job = self._require_job(inference_job_id)
        self._refuse_if_settled(job, "dispatch")
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                UPDATE jobs SET state='RUNNING', worker_id=?, attempt=attempt+1,
                    started_at=?, updated_at=? WHERE inference_job_id=?
                """,
                (worker_id, now, now, inference_job_id),
            )

    def mark_success(
        self,
        inference_job_id: str,
        *,
        raw_output_sha256: str,
        receipt_sha256: str,
        worker_id: str | None = None,
    ) -> None:
        if not raw_output_sha256 or not receipt_sha256:
            raise QueueError("SUCCESS requires both the raw output and receipt hashes")
        job = self._require_job(inference_job_id)
        if job.state == "SUCCESS" and job.raw_output_sha256 != raw_output_sha256:
            raise QueueError(
                f"job {inference_job_id} is already SUCCESS with a different output hash"
            )
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                UPDATE jobs SET state='SUCCESS', raw_output_sha256=?, receipt_sha256=?,
                    error_class=NULL, error_message=NULL, worker_id=COALESCE(?, worker_id),
                    finished_at=?, updated_at=? WHERE inference_job_id=?
                """,
                (raw_output_sha256, receipt_sha256, worker_id, now, now, inference_job_id),
            )

    def mark_failed(
        self,
        inference_job_id: str,
        *,
        error_class: str,
        error_message: str | None = None,
        quarantine: bool = False,
        increment_retry: bool = False,
    ) -> None:
        if error_class not in ERROR_CLASSES:
            raise QueueError(f"error_class {error_class!r} is outside the taxonomy")
        job = self._require_job(inference_job_id)
        self._refuse_if_settled(job, "failure")
        now = utc_now_iso()
        state = "QUARANTINED" if quarantine else "FAILED"
        message = None if error_message is None else error_message[:2000]
        with self._connection:
            self._connection.execute(
                """
                UPDATE jobs SET state=?, error_class=?, error_message=?, finished_at=?,
                    retry_count=retry_count + ?, updated_at=? WHERE inference_job_id=?
                """,
                (state, error_class, message, now, int(increment_retry), now, inference_job_id),
            )

    def requeue(self, inference_job_id: str, *, reason: str) -> None:
        """Return a failed job to PENDING under the same id (MP section 15.9)."""

        job = self._require_job(inference_job_id)
        self._refuse_if_settled(job, f"requeue ({reason})")
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                UPDATE jobs SET state='PENDING', worker_id=NULL, started_at=NULL,
                    finished_at=NULL, updated_at=? WHERE inference_job_id=?
                """,
                (now, inference_job_id),
            )

    def pause_pending(self, *, model_key: str | None = None) -> int:
        """Move dispatchable jobs to PAUSED. In-flight RUNNING jobs are untouched."""

        now = utc_now_iso()
        with self._connection:
            if model_key is None:
                cursor = self._connection.execute(
                    "UPDATE jobs SET state='PAUSED', updated_at=? WHERE state='PENDING'", (now,)
                )
            else:
                cursor = self._connection.execute(
                    """
                    UPDATE jobs SET state='PAUSED', updated_at=?
                    WHERE state='PENDING' AND model_key=?
                    """,
                    (now, model_key),
                )
        return cursor.rowcount

    def resume_paused(self, *, model_key: str | None = None) -> int:
        now = utc_now_iso()
        with self._connection:
            if model_key is None:
                cursor = self._connection.execute(
                    "UPDATE jobs SET state='PENDING', updated_at=? WHERE state='PAUSED'", (now,)
                )
            else:
                cursor = self._connection.execute(
                    """
                    UPDATE jobs SET state='PENDING', updated_at=?
                    WHERE state='PAUSED' AND model_key=?
                    """,
                    (now, model_key),
                )
        return cursor.rowcount

    def counts_by_state(self, *, model_key: str | None = None) -> dict[str, int]:
        if model_key is None:
            rows = self._connection.execute(
                "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT state, COUNT(*) AS n FROM jobs WHERE model_key = ? GROUP BY state",
                (model_key,),
            ).fetchall()
        counts = dict.fromkeys(JOB_STATES, 0)
        for row in rows:
            counts[str(row["state"])] = int(row["n"])
        return counts

    def _require_job(self, inference_job_id: str) -> JobRecord:
        job = self.get_job(inference_job_id)
        if job is None:
            raise QueueError(f"job {inference_job_id} is not in the queue")
        return job

    @staticmethod
    def _refuse_if_settled(job: JobRecord, operation: str) -> None:
        if job.state == "SUCCESS" and job.raw_output_sha256:
            raise QueueError(
                f"refusing {operation}: job {job.inference_job_id} is already SUCCESS "
                "with a frozen output hash (masterplan section 9.3)"
            )
        if job.state == "QUARANTINED":
            raise QueueError(
                f"refusing {operation}: job {job.inference_job_id} is QUARANTINED"
            )

    # -------------------------------------------------------------- shards

    def upsert_shards(self, shards: Iterable[ShardRecord]) -> int:
        now = utc_now_iso()
        written = 0
        with self._connection:
            for shard in shards:
                if shard.state not in SHARD_STATES:
                    raise QueueError(f"shard state must be one of {SHARD_STATES}")
                self._connection.execute(
                    """
                    INSERT INTO shards (shard_id, model_key, benchmark, shard_index, job_count,
                        predicted_seconds, state, worker_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(shard_id) DO UPDATE SET
                        job_count=excluded.job_count,
                        predicted_seconds=excluded.predicted_seconds,
                        updated_at=excluded.updated_at
                    """,
                    (
                        shard.shard_id,
                        shard.model_key,
                        shard.benchmark,
                        shard.shard_index,
                        shard.job_count,
                        shard.predicted_seconds,
                        shard.state,
                        shard.worker_id,
                        now,
                        now,
                    ),
                )
                written += 1
        return written

    def shards_for_model(self, model_key: str) -> tuple[ShardRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM shards WHERE model_key = ? ORDER BY shard_index", (model_key,)
        ).fetchall()
        return tuple(_shard_from_row(row) for row in rows)

    def all_shards(self) -> tuple[ShardRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM shards ORDER BY predicted_seconds DESC, shard_id"
        ).fetchall()
        return tuple(_shard_from_row(row) for row in rows)

    def set_shard_state(
        self, shard_id: str, state: str, *, worker_id: str | None = None
    ) -> None:
        if state not in SHARD_STATES:
            raise QueueError(f"shard state must be one of {SHARD_STATES}")
        with self._connection:
            self._connection.execute(
                "UPDATE shards SET state=?, worker_id=?, updated_at=? WHERE shard_id=?",
                (state, worker_id, utc_now_iso(), shard_id),
            )

    def reserved_shard_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM shards WHERE state IN ('RESERVED','RUNNING')"
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------- workers

    def upsert_worker(self, worker: WorkerRecord) -> None:
        if worker.state not in WORKER_STATES:
            raise QueueError(f"worker state must be one of {WORKER_STATES}")
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO workers (worker_id, model_key, pod_id, replica_index, concurrency,
                    state, jobs_done, jobs_failed, last_heartbeat_at, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    state=excluded.state, concurrency=excluded.concurrency,
                    jobs_done=excluded.jobs_done, jobs_failed=excluded.jobs_failed,
                    last_heartbeat_at=COALESCE(
                        excluded.last_heartbeat_at, workers.last_heartbeat_at),
                    updated_at=excluded.updated_at
                """,
                (
                    worker.worker_id,
                    worker.model_key,
                    worker.pod_id,
                    worker.replica_index,
                    worker.concurrency,
                    worker.state,
                    worker.jobs_done,
                    worker.jobs_failed,
                    worker.last_heartbeat_at,
                    now,
                    now,
                ),
            )

    def workers(self, *, model_key: str | None = None) -> tuple[WorkerRecord, ...]:
        if model_key is None:
            rows = self._connection.execute("SELECT * FROM workers ORDER BY worker_id").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM workers WHERE model_key = ? ORDER BY replica_index", (model_key,)
            ).fetchall()
        return tuple(_worker_from_row(row) for row in rows)

    def set_worker_state(self, worker_id: str, state: str) -> None:
        if state not in WORKER_STATES:
            raise QueueError(f"worker state must be one of {WORKER_STATES}")
        with self._connection:
            self._connection.execute(
                "UPDATE workers SET state=?, updated_at=? WHERE worker_id=?",
                (state, utc_now_iso(), worker_id),
            )

    def record_heartbeat(self, worker_id: str, payload: Mapping[str, object]) -> None:
        now = utc_now_iso()
        state = str(payload.get("stage") or payload.get("state") or "READY")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO heartbeats (worker_id, ts, state, job_id, last_progress_at,
                    gpu_util, vram_used_mb, output_progress)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    worker_id,
                    now,
                    state,
                    _as_optional_str(payload.get("job_id")),
                    _as_optional_str(payload.get("last_progress_at")),
                    _as_optional_float(payload.get("gpu_util")),
                    _as_optional_int(payload.get("vram_used")),
                    _as_optional_int(payload.get("output_progress")),
                ),
            )
            self._connection.execute(
                "UPDATE workers SET last_heartbeat_at=?, state=?, updated_at=? WHERE worker_id=?",
                (now, state if state in WORKER_STATES else "READY", now, worker_id),
            )

    def last_heartbeat(self, worker_id: str) -> Mapping[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM heartbeats WHERE worker_id = ? ORDER BY id DESC LIMIT 1", (worker_id,)
        ).fetchone()
        return None if row is None else dict(row)

    # ---------------------------------------------------------------- pods

    def _add_missing_columns(self) -> None:
        """Add columns a database created before this revision does not have.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op on an existing campaign
        database, so a resumed campaign would otherwise lose the D2/D6 pod
        columns entirely -- and a resume that silently drops the authorization
        trail is exactly the failure the ledger exists to prevent.
        """

        wanted = {
            "provider_api_version": "TEXT",
            "authorization_receipt_path": "TEXT",
            "authorization_receipt_sha256": "TEXT",
            # D57: a campaign database opened before this revision has no
            # gpu_count column. Added with a DEFAULT so every existing row
            # keeps meaning "one GPU" rather than becoming NULL.
            "gpu_count": "INTEGER NOT NULL DEFAULT 1",
        }
        present = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(pods)").fetchall()
        }
        with self._connection:
            for column, kind in wanted.items():
                if column not in present:
                    self._connection.execute(f"ALTER TABLE pods ADD COLUMN {column} {kind}")

    def upsert_pod(self, pod: PodRecord) -> None:
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO pods (pod_id, worker_id, model_key, name, gpu_type, cloud_type,
                    data_center_id, runtime_mode, listed_rate_usd_per_hour, gpu_count,
                    price_snapshot_sha256, provider_api_version,
                    authorization_receipt_path, authorization_receipt_sha256,
                    provisioned_at, model_ready_at,
                    last_job_finished_at, terminated_at, state, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(pod_id) DO UPDATE SET
                    worker_id=COALESCE(excluded.worker_id, pods.worker_id),
                    gpu_type=COALESCE(excluded.gpu_type, pods.gpu_type),
                    cloud_type=COALESCE(excluded.cloud_type, pods.cloud_type),
                    data_center_id=COALESCE(excluded.data_center_id, pods.data_center_id),
                    runtime_mode=COALESCE(excluded.runtime_mode, pods.runtime_mode),
                    listed_rate_usd_per_hour=COALESCE(
                        excluded.listed_rate_usd_per_hour, pods.listed_rate_usd_per_hour),
                    gpu_count=COALESCE(excluded.gpu_count, pods.gpu_count),
                    price_snapshot_sha256=COALESCE(
                        excluded.price_snapshot_sha256, pods.price_snapshot_sha256),
                    provider_api_version=COALESCE(
                        excluded.provider_api_version, pods.provider_api_version),
                    authorization_receipt_path=COALESCE(
                        excluded.authorization_receipt_path, pods.authorization_receipt_path),
                    authorization_receipt_sha256=COALESCE(
                        excluded.authorization_receipt_sha256,
                        pods.authorization_receipt_sha256),
                    model_ready_at=COALESCE(excluded.model_ready_at, pods.model_ready_at),
                    last_job_finished_at=COALESCE(
                        excluded.last_job_finished_at, pods.last_job_finished_at),
                    terminated_at=COALESCE(excluded.terminated_at, pods.terminated_at),
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    pod.pod_id,
                    pod.worker_id,
                    pod.model_key,
                    pod.name,
                    pod.gpu_type,
                    pod.cloud_type,
                    pod.data_center_id,
                    pod.runtime_mode,
                    pod.listed_rate_usd_per_hour,
                    pod.gpu_count,
                    pod.price_snapshot_sha256,
                    pod.provider_api_version,
                    pod.authorization_receipt_path,
                    pod.authorization_receipt_sha256,
                    pod.provisioned_at or now,
                    pod.model_ready_at,
                    pod.last_job_finished_at,
                    pod.terminated_at,
                    pod.state,
                    now,
                ),
            )

    def pods(self, *, live_only: bool = False) -> tuple[PodRecord, ...]:
        if live_only:
            rows = self._connection.execute(
                "SELECT * FROM pods WHERE terminated_at IS NULL ORDER BY pod_id"
            ).fetchall()
        else:
            rows = self._connection.execute("SELECT * FROM pods ORDER BY pod_id").fetchall()
        return tuple(_pod_from_row(row) for row in rows)

    # -------------------------------------------------------------- models

    def set_model_state(
        self,
        model_key: str,
        *,
        state: str,
        canary_status: str = "PENDING",
        full_run_eligible: bool = False,
    ) -> None:
        if state not in CONTROLLER_STATES:
            raise QueueError(f"model state must be one of {CONTROLLER_STATES}")
        if canary_status not in {"PENDING", "PASS", "FAIL"}:
            raise QueueError("canary_status must be PENDING, PASS or FAIL")
        now = utc_now_iso()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO models (model_key, state, canary_status, full_run_eligible, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(model_key) DO UPDATE SET
                    state=excluded.state, canary_status=excluded.canary_status,
                    full_run_eligible=excluded.full_run_eligible, updated_at=excluded.updated_at
                """,
                (model_key, state, canary_status, int(full_run_eligible), now),
            )

    def model_state(self, model_key: str) -> Mapping[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM models WHERE model_key = ?", (model_key,)
        ).fetchone()
        return None if row is None else dict(row)

    def model_states(self) -> tuple[Mapping[str, Any], ...]:
        rows = self._connection.execute("SELECT * FROM models ORDER BY model_key").fetchall()
        return tuple(dict(row) for row in rows)

    # ------------------------------------------------------------ campaign

    def set_flag(self, key: str, value: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO campaign_state (key, value, updated_at) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, utc_now_iso()),
            )

    def flag(self, key: str, default: str | None = None) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM campaign_state WHERE key = ?", (key,)
        ).fetchone()
        return default if row is None else str(row["value"])

    def mirror_event(
        self,
        *,
        entity_kind: str,
        entity_id: str,
        from_state: str | None,
        to_state: str,
        reason: str,
        detail: str | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO events (ts, entity_kind, entity_id, from_state, to_state,
                    reason, detail) VALUES (?,?,?,?,?,?,?)
                """,
                (utc_now_iso(), entity_kind, entity_id, from_state, to_state, reason, detail),
            )

    def events(self, limit: int = 100) -> tuple[Mapping[str, Any], ...]:
        rows = self._connection.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return tuple(dict(row) for row in rows)


# ----------------------------------------------------------------- row maps


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        inference_job_id=str(row["inference_job_id"]),
        model_key=str(row["model_key"]),
        benchmark=str(row["benchmark"]),
        sample_id=str(row["sample_id"]),
        case_key=str(row["case_key"]),
        shard_id=str(row["shard_id"]),
        job_kind=str(row["job_kind"]),
        state=str(row["state"]),
        attempt=int(row["attempt"]),
        retry_count=int(row["retry_count"]),
        error_class=_as_optional_str(row["error_class"]),
        error_message=_as_optional_str(row["error_message"]),
        worker_id=_as_optional_str(row["worker_id"]),
        receipt_sha256=_as_optional_str(row["receipt_sha256"]),
        raw_output_sha256=_as_optional_str(row["raw_output_sha256"]),
        queued_at=str(row["queued_at"]),
        started_at=_as_optional_str(row["started_at"]),
        finished_at=_as_optional_str(row["finished_at"]),
    )


def _shard_from_row(row: sqlite3.Row) -> ShardRecord:
    return ShardRecord(
        shard_id=str(row["shard_id"]),
        model_key=str(row["model_key"]),
        benchmark=str(row["benchmark"]),
        shard_index=int(row["shard_index"]),
        job_count=int(row["job_count"]),
        predicted_seconds=float(row["predicted_seconds"]),
        state=str(row["state"]),
        worker_id=_as_optional_str(row["worker_id"]),
    )


def _worker_from_row(row: sqlite3.Row) -> WorkerRecord:
    return WorkerRecord(
        worker_id=str(row["worker_id"]),
        model_key=str(row["model_key"]),
        pod_id=str(row["pod_id"]),
        replica_index=int(row["replica_index"]),
        concurrency=int(row["concurrency"]),
        state=str(row["state"]),
        jobs_done=int(row["jobs_done"]),
        jobs_failed=int(row["jobs_failed"]),
        last_heartbeat_at=_as_optional_str(row["last_heartbeat_at"]),
    )


def _pod_from_row(row: sqlite3.Row) -> PodRecord:
    return PodRecord(
        pod_id=str(row["pod_id"]),
        model_key=str(row["model_key"]),
        name=str(row["name"]),
        state=str(row["state"]),
        worker_id=_as_optional_str(row["worker_id"]),
        gpu_type=_as_optional_str(row["gpu_type"]),
        cloud_type=_as_optional_str(row["cloud_type"]),
        data_center_id=_as_optional_str(row["data_center_id"]),
        runtime_mode=_as_optional_str(row["runtime_mode"]),
        listed_rate_usd_per_hour=_as_optional_float(row["listed_rate_usd_per_hour"]),
        gpu_count=_as_optional_int(row["gpu_count"]) or 1,
        price_snapshot_sha256=_as_optional_str(row["price_snapshot_sha256"]),
        provider_api_version=_as_optional_str(row["provider_api_version"]),
        authorization_receipt_path=_as_optional_str(row["authorization_receipt_path"]),
        authorization_receipt_sha256=_as_optional_str(row["authorization_receipt_sha256"]),
        provisioned_at=_as_optional_str(row["provisioned_at"]),
        model_ready_at=_as_optional_str(row["model_ready_at"]),
        last_job_finished_at=_as_optional_str(row["last_job_finished_at"]),
        terminated_at=_as_optional_str(row["terminated_at"]),
    )


def _as_optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _as_optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def unique_case_keys(jobs: Sequence[JobRecord]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(job.case_key for job in jobs))
