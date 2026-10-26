"""Loopback multi-process reference experiment; central coordinator baseline.

This is a bounded benchmark harness for deterministic SHA-256 work. It is not
a robot controller, decentralized system, or exactly-once execution engine.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core import ValidationError

MAX_WORKERS = 16
MAX_TASKS = 100
MAX_ITERATIONS = 100_000
MAX_TOTAL_WORK = 500_000
MAX_TIMEOUT_S = 300.0
MAX_BODY = 16_384
MAX_ATTEMPTS = 5
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _valid_positive_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValidationError(f"{name} must be an integer from 1 to {maximum}")
    return value


def _make_tasks(count: int, iterations: int) -> list[dict[str, Any]]:
    tasks = []
    for number in range(count):
        task_id = f"task-{number:04d}"
        seed = hashlib.sha256(f"prime-components-v0.2:{task_id}".encode("ascii")).hexdigest()
        tasks.append({"task_id": task_id, "seed": seed, "iterations": iterations})
    return tasks


def _oracle_digest(seed: str, iterations: int) -> str:
    """Independent serial oracle, separate from the worker implementation."""
    block = bytes.fromhex(seed)
    for index in range(iterations):
        h = hashlib.sha256()
        h.update(block)
        h.update(index.to_bytes(4, "big"))
        block = h.digest()
    return block.hex()


class CoordinatorState:
    """Thread-safe lease/fencing state exposed for protocol validation tests."""

    def __init__(self, tasks: list[dict[str, Any]], expected: dict[str, str] | None = None,
                 *, reserved_task_id: str | None = None):
        self.lock = threading.RLock()
        self.tasks = {task["task_id"]: {"task": dict(task), "status": "pending", "attempt": 0,
                                        "session": None, "token": None}
                      for task in tasks}
        self.expected = expected or {}
        self.started_at = time.monotonic()
        self.reserved_task_id = reserved_task_id
        self.pool_released = False
        self.hello_count = 0
        self.worker_sequence = 0
        self.sessions: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.first_dispatch_at: float | None = None
        self.completed_at: float | None = None
        self.failure_injected_at: float | None = None
        self.first_retry_at: float | None = None
        self.failure_ready = threading.Event()

    def _event(self, event: str, session: str | None = None, **fields: Any) -> None:
        self.events.append({"seq": len(self.events) + 1,
                            "t_rel_s": max(0.0, time.monotonic() - self.started_at),
                            "worker": self.sessions.get(session, {}).get("label", "coordinator") if session else "coordinator",
                            "event": event, **fields})

    def record(self, event: str, session: str | None = None, **fields: Any) -> None:
        with self.lock:
            self._event(event, session, **fields)

    def register_worker(self, session: str, *, hold_before_compute: bool = False) -> None:
        if not _HEX32.fullmatch(session):
            raise ValueError("invalid worker session")
        with self.lock:
            label = f"worker-{self.worker_sequence:04d}"
            self.worker_sequence += 1
            self.sessions[session] = {"active": True, "hold": hold_before_compute,
                                      "go": threading.Event(), "ready": False,
                                      "hello": False, "claimed": False, "completed": False,
                                      "label": label, "exit_confirmed": False}
            self._event("worker_registered", session)

    def hello(self, session: str) -> bool:
        with self.lock:
            worker = self.sessions.get(session)
            if not worker or not worker["active"]:
                return False
            if not worker["hello"]:
                worker["hello"] = True
                self.hello_count += 1
                self._event("worker_http_hello", session)
            return True

    def release_pool(self) -> None:
        with self.lock:
            self.pool_released = True
            self._event("worker_pool_claim_gate_released", ready_workers=self.hello_count)

    def gate_ready(self, session: str) -> bool:
        with self.lock:
            worker = self.sessions.get(session)
            return bool(worker and worker["active"] and worker["hello"] and self.pool_released)

    def claim(self, session: str) -> dict[str, Any]:
        with self.lock:
            worker = self.sessions.get(session)
            if worker is None or not worker["active"]:
                return {"error": "inactive worker"}
            if not self.pool_released or not worker["hello"]:
                return {"wait": True}
            for task_id, entry in self.tasks.items():
                if entry["status"] != "pending":
                    continue
                if task_id == self.reserved_task_id and session != next(
                        (sid for sid, item in self.sessions.items() if item["hold"]), None):
                    continue
                if session in self.sessions and self.sessions[session]["hold"] and task_id != self.reserved_task_id:
                    # A reserved failure worker only receives task zero.
                    continue
                if entry["attempt"] >= MAX_ATTEMPTS:
                    entry["status"] = "failed"
                    continue
                entry["status"] = "leased"
                entry["attempt"] += 1
                entry["session"] = session
                entry["token"] = secrets.token_hex(16)
                if self.first_dispatch_at is None:
                    self.first_dispatch_at = time.monotonic()
                worker["claimed"] = True
                self._event("task_leased", session, task_id=task_id, attempt=entry["attempt"])
                return {"job": {**entry["task"], "attempt": entry["attempt"],
                                 "fencing_token": entry["token"],
                                 "hold_before_compute": worker["hold"]}}
            if all(entry["status"] == "completed" for entry in self.tasks.values()):
                return {"stop": True}
            return {"job": None}

    def mark_ready(self, session: str, task_id: Any, attempt: Any, token: Any) -> bool:
        with self.lock:
            worker = self.sessions.get(session)
            entry = self.tasks.get(task_id) if isinstance(task_id, str) else None
            if not worker or not worker["active"] or not worker["hold"] or not entry:
                return False
            if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                return False
            if entry["status"] != "leased" or entry["session"] != session:
                return False
            if entry["attempt"] != attempt or entry["token"] != token:
                return False
            worker["ready"] = True
            self.failure_ready.set()
            self._event("failure_worker_at_precompute_barrier", session,
                        task_id=task_id, attempt=attempt)
            return True

    def wait_for_go(self, session: str, task_id: str, timeout_s: float = 30.0) -> bool:
        with self.lock:
            worker = self.sessions.get(session)
            entry = self.tasks.get(task_id)
            if not worker or not entry or entry["session"] != session:
                return False
            gate = worker["go"]
        gate.wait(timeout_s)
        with self.lock:
            worker = self.sessions.get(session)
            entry = self.tasks.get(task_id)
            return bool(worker and worker["active"] and entry and entry["status"] == "leased"
                        and entry["session"] == session and gate.is_set())

    def accept_result(self, task_id: Any, session: str, attempt: Any,
                      fencing_token: Any, digest: Any) -> tuple[bool, str]:
        with self.lock:
            entry = self.tasks.get(task_id) if isinstance(task_id, str) else None
            worker = self.sessions.get(session)
            if entry is None:
                return False, "unknown_task"
            if worker is None or not worker["active"]:
                return False, "inactive_worker"
            if entry["status"] != "leased":
                return False, "task_not_leased"
            if entry["session"] != session:
                return False, "wrong_worker"
            if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                return False, "invalid_attempt"
            if entry["attempt"] != attempt or not isinstance(fencing_token, str) or entry["token"] != fencing_token:
                return False, "stale_fencing_token"
            if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
                return False, "invalid_digest"
            expected = self.expected.get(task_id)
            if expected is not None and digest != expected:
                return False, "digest_mismatch"
            entry["status"] = "completed"
            entry["digest"] = digest
            worker["completed"] = True
            if attempt > 1 and self.first_retry_at is None:
                self.first_retry_at = time.monotonic()
            self._event("result_accepted", session, task_id=task_id, attempt=attempt)
            if all(item["status"] == "completed" for item in self.tasks.values()):
                self.completed_at = time.monotonic()
            return True, "accepted"

    def worker_exited(self, session: str) -> None:
        with self.lock:
            worker = self.sessions.get(session)
            if not worker or worker["exit_confirmed"]:
                return
            worker["active"] = False
            worker["exit_confirmed"] = True
            worker["go"].set()
            self._event("worker_process_exit_confirmed", session)
            for task_id, entry in self.tasks.items():
                if entry["status"] == "leased" and entry["session"] == session:
                    if entry["attempt"] >= MAX_ATTEMPTS:
                        entry["status"] = "failed"
                        self._event("lease_failed_attempt_limit", session, task_id=task_id,
                                    attempt=entry["attempt"])
                    else:
                        entry["status"] = "pending"
                        entry["session"] = None
                        entry["token"] = None
                        if task_id == self.reserved_task_id:
                            self.reserved_task_id = None
                        self._event("lease_reclaimed_after_confirmed_process_exit", session,
                                    task_id=task_id, attempt=entry["attempt"])

    def request_failure(self, session: str, task_id: str) -> None:
        with self.lock:
            self.failure_injected_at = time.monotonic()
            self._event("failure_injection_requested", session, task_id=task_id)

    def begin_shutdown(self) -> None:
        with self.lock:
            for session, worker in self.sessions.items():
                if worker["active"]:
                    worker["active"] = False
                    worker["go"].set()
                    self._event("worker_shutdown_requested", session)

    def worker_summary(self) -> dict[str, Any]:
        with self.lock:
            workers = list(self.sessions.values())
            return {"workers_started": len(workers),
                    "workers_hello_ready": sum(1 for worker in workers if worker["hello"]),
                    "workers_claimed": sorted(worker["label"] for worker in workers if worker["claimed"]),
                    "workers_completed": sorted(worker["label"] for worker in workers if worker["completed"])}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"events": list(self.events),
                    "results": {tid: entry["digest"] for tid, entry in self.tasks.items()
                                if entry["status"] == "completed"},
                    "task_results": {tid: {"digest": entry["digest"], "attempt": entry["attempt"]}
                                     for tid, entry in self.tasks.items()
                                     if entry["status"] == "completed"},
                    "completed": self.completed_at is not None,
                    "failed_tasks": [tid for tid, entry in self.tasks.items() if entry["status"] == "failed"]}


def _make_handler(state: CoordinatorState, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(2.0)

        def log_message(self, fmt: str, *args: Any) -> None:
            # Do not log headers, tokens, local paths, or user data.
            return

        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self) -> str | None:
            session = self.headers.get("X-Worker-Session", "")
            supplied = self.headers.get("X-Experiment-Token", "")
            if not secrets.compare_digest(supplied, token) or not _HEX32.fullmatch(session):
                return None
            return session

        def do_GET(self) -> None:
            session = self.authorized()
            if session is None:
                self.send_json(403, {"error": "unauthorized"})
                return
            parsed = urlparse(self.path)
            if parsed.path == "/claim":
                self.send_json(200, state.claim(session))
            elif parsed.path == "/hello":
                self.send_json(200, {"hello": state.hello(session)})
            elif parsed.path == "/gate":
                self.send_json(200, {"released": state.gate_ready(session)})
            elif parsed.path == "/go":
                query = parse_qs(parsed.query)
                task_ids = query.get("task_id", [])
                go = state.wait_for_go(session, task_ids[0], timeout_s=25.0) if len(task_ids) == 1 else False
                self.send_json(200, {"go": go})
            else:
                self.send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            session = self.authorized()
            if session is None:
                self.send_json(403, {"error": "unauthorized"})
                return
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if not 0 <= size <= MAX_BODY:
                self.send_json(413, {"error": "body_too_large_or_missing"})
                return
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("partial body")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("object required")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError, socket.timeout):
                self.send_json(400, {"error": "invalid_json_object"})
                return
            if self.path == "/ready":
                ready = state.mark_ready(session, payload.get("task_id"), payload.get("attempt"), payload.get("fencing_token"))
                self.send_json(200, {"ready": ready})
            elif self.path == "/result":
                accepted, reason = state.accept_result(payload.get("task_id"), session,
                                                       payload.get("attempt"), payload.get("fencing_token"),
                                                       payload.get("digest"))
                self.send_json(200 if accepted else 409, {"accepted": accepted, "reason": reason})
            else:
                self.send_json(404, {"error": "not_found"})

    return Handler


class _QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        # A deliberately terminated worker can reset its waiting HTTP socket.
        return


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)


def _wait_for_hellos(state: CoordinatorState, processes: dict[str, subprocess.Popen[bytes]],
                     target: int, deadline: float) -> tuple[bool, str | None]:
    while _remaining(deadline) > 0:
        summary = state.worker_summary()
        if summary["workers_hello_ready"] == target:
            return True, None
        for session, proc in processes.items():
            if proc.poll() is not None and not state.sessions[session]["exit_confirmed"]:
                state.worker_exited(session)
                return False, "worker exited before its HTTP hello completed"
        time.sleep(min(0.005, max(0.0, _remaining(deadline))))
    return False, "shared deadline expired waiting for worker HTTP hello"


def _scenario(workers: int, tasks: list[dict[str, Any]], expected: dict[str, str],
              deadline: float, *, inject_failure: bool, fail_all_workers: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    state = CoordinatorState(tasks, expected,
                             reserved_task_id=tasks[0]["task_id"] if inject_failure else None)
    token = secrets.token_hex(32)
    server: _QuietHTTPServer | None = None
    server_thread: threading.Thread | None = None
    processes: dict[str, subprocess.Popen[bytes]] = {}
    failure_at: float | None = None
    status = "running"
    reason = None

    def spawn(index: int, *, held: bool = False) -> str:
        session = secrets.token_hex(16)
        state.register_worker(session, hold_before_compute=held)
        env = dict(os.environ)
        env["PRIME_COMPONENTS_EXPERIMENT_TOKEN"] = token
        project_root = Path(__file__).resolve().parent.parent
        assert server is not None
        proc = subprocess.Popen([sys.executable, "-m", "prime_components.worker", str(server.server_address[1]), session],
                                cwd=project_root, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes[session] = proc
        return session

    def cleanup() -> dict[str, bool]:
        state.begin_shutdown()
        for proc in processes.values():
            if proc.poll() is None:
                proc.terminate()
        for session, proc in processes.items():
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
            state.worker_exited(session)
        if server is not None:
            if server_thread is not None and server_thread.is_alive():
                server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=1.0)
        return {"all_workers_stopped": all(proc.poll() is not None for proc in processes.values()),
                "server_thread_stopped": server_thread is None or not server_thread.is_alive()}

    cleanup_report = {"all_workers_stopped": True, "server_thread_stopped": True}
    try:
        server = _QuietHTTPServer(("127.0.0.1", 0), _make_handler(state, token))
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        server_thread.start()
        sessions = [spawn(i, held=inject_failure and i == 0) for i in range(workers)]
        ready, hello_error = _wait_for_hellos(state, processes, workers, deadline)
        if not ready:
            status, reason = ("timed_out", hello_error) if _remaining(deadline) <= 0 else ("failed", hello_error)
        else:
            state.release_pool()

        failed_session = sessions[0] if inject_failure else None
        if status == "running" and inject_failure:
            while not state.failure_ready.is_set() and _remaining(deadline) > 0:
                if processes[failed_session].poll() is not None:
                    state.worker_exited(failed_session)
                    status, reason = "failed", "designated worker exited before reaching the precompute barrier"
                    break
                state.failure_ready.wait(timeout=min(0.01, max(0.0, _remaining(deadline))))
            if status == "running" and not state.failure_ready.is_set():
                status, reason = "timed_out", "shared deadline expired waiting for deterministic failure barrier"
            if status == "running":
                state.request_failure(failed_session, tasks[0]["task_id"])
                failure_at = state.failure_injected_at
                if fail_all_workers:
                    # Atomically close the whole pool before the failed lease is
                    # returned to pending, so no survivor can claim or submit it.
                    state.begin_shutdown()
                _terminate(processes[failed_session])
                state.worker_exited(failed_session)
                if fail_all_workers:
                    # Test hook proves that every originally launched worker is stopped.
                    for session, proc in processes.items():
                        if session != failed_session:
                            _terminate(proc)
                            state.worker_exited(session)
                    status, reason = "failed", "no_live_workers_after_injected_failure"

        while status == "running":
            snap = state.snapshot()
            if snap["completed"]:
                status = "completed"
                break
            if snap["failed_tasks"]:
                status, reason = "failed", "task exceeded the bounded attempt limit"
                break
            if _remaining(deadline) <= 0:
                status, reason = "timed_out", "shared experiment deadline expired"
                break
            for session, proc in list(processes.items()):
                if proc.poll() is not None and state.sessions.get(session, {}).get("active"):
                    state.worker_exited(session)
            if not any(worker["active"] for worker in state.sessions.values()) and not snap["completed"]:
                status, reason = "failed", "no_live_workers"
                break
            if status != "running":
                break
            time.sleep(0.005)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        status, reason = "failed", f"runtime infrastructure error: {type(exc).__name__}"
    finally:
        try:
            cleanup_report = cleanup()
        except (OSError, RuntimeError, subprocess.SubprocessError):
            cleanup_report = {"all_workers_stopped": all(proc.poll() is not None for proc in processes.values()),
                              "server_thread_stopped": server_thread is None or not server_thread.is_alive()}

    snapshot = state.snapshot()
    worker_summary = state.worker_summary()
    ended = time.monotonic()
    completed_at = state.completed_at
    dispatch_at = state.first_dispatch_at
    fault_first_retry = (state.first_retry_at - failure_at) if state.first_retry_at is not None and failure_at is not None else None
    fault_complete = (completed_at - failure_at) if completed_at is not None and failure_at is not None else None
    result = {"status": status, "workers": workers, **worker_summary,
              "workers_started": len(processes),
              "cleanup": cleanup_report,
              "wall_s": (completed_at - started) if completed_at is not None else (ended - started),
              "dispatch_to_complete_s": (completed_at - dispatch_at) if completed_at is not None and dispatch_at is not None else None,
              "failure_to_first_retry_success_s": fault_first_retry,
              "failure_to_all_complete_s": fault_complete,
              "results": snapshot["results"], "task_results": snapshot["task_results"],
              "events": snapshot["events"]}
    if reason:
        result["reason"] = reason
    return result


def run_experiment(workers: int = 3, tasks: int = 12, iterations: int = 20_000,
                   inject_failure: bool = True, timeout_s: float = 30.0,
                   *, fail_all_workers: bool = False) -> dict[str, Any]:
    """Run single-worker, healthy parallel, and fault/recovery scenarios.

    ``timeout_s`` is one shared deadline for all runtime scenarios, including
    process startup. The bounded pure-Python result oracle is built before that
    runtime deadline and is reported separately from measured scenario times.
    ``fail_all_workers`` is a test hook that terminates every initially started
    worker after the injected failure and returns a finite ``failed`` report.
    """
    workers = _valid_positive_int(workers, "workers", MAX_WORKERS)
    tasks = _valid_positive_int(tasks, "tasks", MAX_TASKS)
    iterations = _valid_positive_int(iterations, "iterations", MAX_ITERATIONS)
    if inject_failure and workers < 2:
        raise ValidationError("workers must be >= 2 when failure injection is enabled")
    if tasks * iterations > MAX_TOTAL_WORK:
        raise ValidationError(f"tasks * iterations must be <= {MAX_TOTAL_WORK}")
    try:
        timeout_value = float(timeout_s)
    except (OverflowError, ValueError, TypeError):
        raise ValidationError(f"timeout_s must be finite and in (0, {MAX_TIMEOUT_S}]")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_value) or not 0 < timeout_value <= MAX_TIMEOUT_S:
        raise ValidationError(f"timeout_s must be finite and in (0, {MAX_TIMEOUT_S}]")
    if not isinstance(inject_failure, bool) or not isinstance(fail_all_workers, bool):
        raise ValidationError("inject_failure and fail_all_workers must be bools")
    if fail_all_workers and not inject_failure:
        raise ValidationError("fail_all_workers requires inject_failure=True")

    oracle_start = time.monotonic()
    work = _make_tasks(tasks, iterations)
    expected = {task["task_id"]: _oracle_digest(task["seed"], task["iterations"]) for task in work}
    oracle_s = time.monotonic() - oracle_start
    deadline = time.monotonic() + float(timeout_s)
    single = _scenario(1, work, expected, deadline, inject_failure=False)
    def skipped(worker_count: int) -> dict[str, Any]:
        return {"status": "timed_out", "workers": worker_count, "workers_started": 0,
                "workers_hello_ready": 0, "workers_claimed": [], "workers_completed": [],
                "cleanup": {"all_workers_stopped": True, "server_thread_stopped": True},
                "wall_s": 0.0, "dispatch_to_complete_s": None,
                "failure_to_first_retry_success_s": None, "failure_to_all_complete_s": None,
                "results": {}, "task_results": {}, "events": [],
                "reason": "shared experiment deadline expired before scenario start"}
    healthy = _scenario(workers, work, expected, deadline, inject_failure=False) if _remaining(deadline) > 0 else skipped(workers)
    fault = None
    if inject_failure:
        fault = _scenario(workers, work, expected, deadline, inject_failure=True,
                          fail_all_workers=fail_all_workers) if _remaining(deadline) > 0 else skipped(workers)
    outputs = {"single_worker": single, "multi_worker": healthy}
    if fault is not None:
        outputs["multi_worker_failure"] = fault
    baseline = single.get("results", {}) if single.get("status") == "completed" else {}
    for name, scenario in outputs.items():
        scenario["matches_single_worker"] = scenario.get("status") == "completed" and scenario.get("results") == baseline
        scenario["correct_against_oracle"] = scenario.get("status") == "completed" and scenario.get("results") == expected
    all_completed = all(scenario["status"] == "completed" for scenario in outputs.values())
    all_match = all(scenario["matches_single_worker"] and scenario["correct_against_oracle"]
                    and scenario.get("cleanup", {}).get("all_workers_stopped")
                    and scenario.get("cleanup", {}).get("server_thread_stopped")
                    for scenario in outputs.values())
    all_correct = all_completed and all_match
    return {"model": "independent Python worker processes over loopback HTTP/JSON; central coordinator baseline",
            "status": "completed" if all_correct else "timed_out" if any(s["status"] == "timed_out" for s in outputs.values()) else "failed",
            "all_correct": all_correct,
            "scope": "synthetic deterministic SHA-256 tasks only; no robot control, decentralized coordination, or exactly-once execution; leases are reclaimed only after confirmed worker-process exit, with no TTL/hung-worker/network-partition detector",
            "environment": {"python": platform.python_version(), "os": platform.system(),
                            "cpu_count": os.cpu_count()},
            "deadline": {"timeout_s": float(timeout_s), "scope": "shared across all runtime scenarios and worker startup; bounded expected-output oracle excluded"},
            "parameters": {"workers": workers, "tasks": tasks, "iterations_per_task": iterations,
                           "inject_failure": inject_failure, "fail_all_workers_test_hook": fail_all_workers,
                           "oracle_validation_s": oracle_s, "work_cap_tasks_times_iterations": MAX_TOTAL_WORK},
            "work_definition": "Repeated SHA-256: digest = SHA256(previous_digest || uint32_be(iteration)); task seed derived deterministically from task id.",
            "timing_notes": {"wall_s": "startup-inclusive scenario time to all accepted task results; one observation, not a speedup claim",
                             "dispatch_to_complete_s": "first task claim to all accepted task results",
                             "failure_recovery": "interval starts at failure_injection_requested before terminate and ends at accepted retry/completion; harness recovery only, not physical MTTR"},
            "scenarios": outputs}
