"""Restricted loopback worker process for the runtime experiment.

Workers accept only a small JSON task describing repeated SHA-256 operations.
No Python objects, shell commands, or user-provided code cross the protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MAX_BODY = 16_384
MAX_ITERATIONS = 100_000
_HEX = re.compile(r"^[0-9a-f]{64}$")


def calculate_digest(seed: str, iterations: int) -> str:
    if not isinstance(seed, str) or not _HEX.fullmatch(seed):
        raise ValueError("seed must be a 64-character lowercase hex digest")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 0 <= iterations <= MAX_ITERATIONS:
        raise ValueError("iterations is outside the supported range")
    value = bytes.fromhex(seed)
    for index in range(iterations):
        value = hashlib.sha256(value + index.to_bytes(4, "big")).digest()
    return value.hex()


class WorkerClient:
    def __init__(self, port: int, session: str, token: str):
        self.base = f"http://127.0.0.1:{port}"
        self.session = session
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.headers = {"X-Worker-Session": session, "X-Experiment-Token": token}

    def request(self, route: str, payload: dict[str, Any] | None = None, timeout: float = 1.0) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + route, data=data, headers=headers)
        with self.opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError("server response exceeds the size limit")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("server response must be a JSON object")
        return result

    def run(self) -> int:
        try:
            hello = self.request("/hello", timeout=2.0)
            if not hello.get("hello"):
                return 3
            while not self.request("/gate", timeout=2.0).get("released"):
                time.sleep(0.005)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            return 3
        while True:
            try:
                reply = self.request("/claim", timeout=2.0)
                if reply.get("stop"):
                    return 0
                if reply.get("wait"):
                    time.sleep(0.005)
                    continue
                job = reply.get("job")
                if job is None:
                    time.sleep(0.01)
                    continue
                if not isinstance(job, dict):
                    return 2
                task_id = job.get("task_id")
                seed = job.get("seed")
                iterations = job.get("iterations")
                attempt = job.get("attempt")
                fencing = job.get("fencing_token")
                if not isinstance(task_id, str) or not task_id or len(task_id) > 80:
                    return 2
                if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                    return 2
                if not isinstance(fencing, str) or not re.fullmatch(r"[0-9a-f]{32}", fencing):
                    return 2
                if job.get("hold_before_compute"):
                    ready = self.request("/ready", {"task_id": task_id, "attempt": attempt, "fencing_token": fencing})
                    if not ready.get("ready"):
                        continue
                    # A deterministic barrier: no computation starts until the
                    # coordinator explicitly releases this lease. Fault tests kill
                    # this process while it is waiting here.
                    release = self.request("/go?task_id=" + urllib.parse.quote(task_id), timeout=30.0)
                    if not release.get("go"):
                        continue
                digest = calculate_digest(seed, iterations)
                self.request("/result", {"task_id": task_id, "attempt": attempt,
                                         "fencing_token": fencing, "digest": digest})
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
                return 3


def main() -> int:
    # argv contains only a loopback port and opaque worker session, never a token.
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        return 2
    port = int(sys.argv[1])
    session = sys.argv[2]
    token = os.environ.pop("PRIME_COMPONENTS_EXPERIMENT_TOKEN", "")
    if not 0 < port < 65536 or not re.fullmatch(r"[0-9a-f]{32}", session) or not re.fullmatch(r"[0-9a-f]{64}", token):
        return 2
    return WorkerClient(port, session, token).run()


if __name__ == "__main__":
    raise SystemExit(main())
