"""Model-isolated endpoint pool and worker topology contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock


class WorkerType(StrEnum):
    ACTIVE_WARM = "active_warm"
    FLEX = "flex"
    CPU_EVALUATOR = "cpu_evaluator"
    ORCHESTRATOR = "orchestrator"


@dataclass(frozen=True, slots=True)
class RuntimeStack:
    runtime_image_digest: str
    framework: str
    cuda_version: str | None
    serving_runtime: str

    def __post_init__(self) -> None:
        if not self.runtime_image_digest or not self.framework or not self.serving_runtime:
            raise ValueError("runtime stack identity fields are required")


@dataclass(frozen=True, slots=True)
class EndpointPool:
    pool_id: str
    model_revision: str
    worker_type: WorkerType
    runtime_stack: RuntimeStack
    capabilities: frozenset[str]
    minimum_workers: int
    maximum_workers: int

    def __post_init__(self) -> None:
        if not self.pool_id or not self.model_revision or not self.capabilities:
            raise ValueError("endpoint pool identity and capabilities are required")
        if self.minimum_workers < 0 or self.maximum_workers < 1:
            raise ValueError("endpoint pool worker bounds are invalid")
        if self.minimum_workers > self.maximum_workers:
            raise ValueError("minimum workers cannot exceed maximum workers")
        if self.worker_type is WorkerType.ACTIVE_WARM and self.minimum_workers < 1:
            raise ValueError("active warm pools require at least one resident worker")
        if self.worker_type is WorkerType.FLEX and self.minimum_workers != 0:
            raise ValueError("flex pools must support scale-to-zero")


@dataclass(frozen=True, slots=True)
class PoolWorker:
    worker_id: str
    pool_id: str
    model_revision: str
    runtime_stack: RuntimeStack
    gpu_type: str | None

    def __post_init__(self) -> None:
        if not self.worker_id or not self.pool_id or not self.model_revision:
            raise ValueError("pool worker identity fields are required")


class PoolConflictError(RuntimeError):
    pass


class EndpointPoolRegistry:
    """Prevents framework, image, CUDA, or model drift inside one pool."""

    def __init__(self) -> None:
        self._pools: dict[str, EndpointPool] = {}
        self._workers: dict[str, PoolWorker] = {}
        self._lock = RLock()

    def register_pool(self, pool: EndpointPool) -> EndpointPool:
        with self._lock:
            existing = self._pools.get(pool.pool_id)
            if existing is not None and existing != pool:
                raise PoolConflictError("endpoint pool contract cannot be mutated")
            self._pools[pool.pool_id] = pool
            return pool

    def attach_worker(self, worker: PoolWorker) -> PoolWorker:
        with self._lock:
            pool = self._pools.get(worker.pool_id)
            if pool is None:
                raise KeyError(worker.pool_id)
            if worker.model_revision != pool.model_revision:
                raise PoolConflictError("worker model revision does not match its endpoint pool")
            if worker.runtime_stack != pool.runtime_stack:
                raise PoolConflictError("worker runtime stack does not match its endpoint pool")
            existing = self._workers.get(worker.worker_id)
            if existing is not None:
                if existing != worker:
                    raise PoolConflictError("worker identity cannot move between endpoint pools")
                return existing
            worker_count = sum(
                registered.pool_id == pool.pool_id for registered in self._workers.values()
            )
            if worker_count >= pool.maximum_workers:
                raise PoolConflictError("endpoint pool maximum worker capacity exceeded")
            self._workers[worker.worker_id] = worker
            return worker

    def workers(self, pool_id: str) -> tuple[PoolWorker, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        worker
                        for worker in self._workers.values()
                        if worker.pool_id == pool_id
                    ),
                    key=lambda worker: worker.worker_id,
                )
            )


__all__ = [
    "EndpointPool",
    "EndpointPoolRegistry",
    "PoolConflictError",
    "PoolWorker",
    "RuntimeStack",
    "WorkerType",
]
