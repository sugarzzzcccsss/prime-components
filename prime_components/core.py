from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

MAX_MODULES = 20
MAX_NODES = 1_000_000_000
MAX_ROUNDS = 1_000_000_000
STATUSES = {"ready", "fault", "offline"}


class ValidationError(ValueError):
    """Input violates the reference model's documented schema or bounds."""


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{where} must be an object")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where} must be a non-empty string")
    return value


def _finite_number(value: Any, where: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValidationError(f"{where} must be finite and >= {minimum}")
    if not math.isfinite(number) or number < minimum:
        raise ValidationError(f"{where} must be finite and >= {minimum}")
    return number


def validate_catalog(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = _object(data, "input")
    modules = root.get("modules")
    tasks = root.get("tasks")
    if not isinstance(modules, list) or not isinstance(tasks, list):
        raise ValidationError("modules and tasks must be arrays")
    if len(modules) > MAX_MODULES:
        raise ValidationError(f"at most {MAX_MODULES} modules are supported")
    clean_modules = []
    ids: set[str] = set()
    for i, raw in enumerate(modules):
        item = _object(raw, f"modules[{i}]")
        mid = _string(item.get("id"), f"modules[{i}].id")
        if mid in ids:
            raise ValidationError(f"duplicate module id: {mid}")
        ids.add(mid)
        kind = _string(item.get("type"), f"modules[{i}].type")
        caps = item.get("capabilities")
        if not isinstance(caps, list) or not caps:
            raise ValidationError(f"modules[{i}].capabilities must be a non-empty array")
        capset = set()
        for cap in caps:
            capset.add(_string(cap, f"modules[{i}].capabilities item"))
        interface = _string(item.get("interface"), f"modules[{i}].interface")
        power = _finite_number(item.get("power_w"), f"modules[{i}].power_w")
        status = item.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValidationError(f"modules[{i}].status must be ready, fault, or offline")
        clean_modules.append({"id": mid, "type": kind, "capabilities": capset,
                              "interface": interface, "power_w": power, "status": status})
    clean_tasks = []
    task_ids: set[str] = set()
    for i, raw in enumerate(tasks):
        item = _object(raw, f"tasks[{i}]")
        tid = _string(item.get("id"), f"tasks[{i}].id")
        if tid in task_ids:
            raise ValidationError(f"duplicate task id: {tid}")
        task_ids.add(tid)
        needs = item.get("need")
        if not isinstance(needs, dict) or not needs:
            raise ValidationError(f"tasks[{i}].need must be a non-empty object")
        clean_need = {}
        for cap, count in needs.items():
            _string(cap, f"tasks[{i}].need capability")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValidationError(f"tasks[{i}].need[{cap}] must be a positive integer")
            clean_need[cap] = count
        clean_tasks.append({"id": tid, "need": clean_need,
                            "interface": _string(item.get("interface"), f"tasks[{i}].interface"),
                            "power_budget_w": _finite_number(item.get("power_budget_w"), f"tasks[{i}].power_budget_w")})
    return clean_modules, clean_tasks


def choose_modules(modules: list[dict[str, Any]], task: dict[str, Any]) -> dict[str, Any]:
    """Exhaustive capability cover, ranked by type-count, instance-count, power, IDs."""
    if len(modules) > MAX_MODULES:
        raise ValidationError(f"at most {MAX_MODULES} modules are supported")
    eligible = [m for m in modules if m["status"] == "ready" and m["interface"] == task["interface"]]
    best = None
    for size in range(1, len(eligible) + 1):
        for subset in itertools.combinations(eligible, size):
            if sum(m["power_w"] for m in subset) > task["power_budget_w"]:
                continue
            counts: dict[str, int] = {}
            for module in subset:
                for capability in module["capabilities"]:
                    counts[capability] = counts.get(capability, 0) + 1
            if any(counts.get(cap, 0) < needed for cap, needed in task["need"].items()):
                continue
            ids = tuple(sorted(m["id"] for m in subset))
            rank = (len({m["type"] for m in subset}), len(subset), sum(m["power_w"] for m in subset), ids)
            if best is None or rank < best[0]:
                best = (rank, subset)
    if best is None:
        return {"feasible": False, "task_id": task["id"], "selected": [], "reason": "no ready compatible module set meets capability counts and power budget"}
    chosen = sorted(best[1], key=lambda m: m["id"])
    return {"feasible": True, "task_id": task["id"], "selected": [m["id"] for m in chosen],
            "types": sorted({m["type"] for m in chosen}), "power_w": sum(m["power_w"] for m in chosen)}


def validate_compute(params: Any) -> dict[str, Any]:
    p = _object(params, "compute parameters")
    t1 = _finite_number(p.get("T1"), "T1", minimum=0.000000000001)
    serial = _finite_number(p.get("f"), "f")
    if serial > 1:
        raise ValidationError("f must be in [0, 1]")
    for name in ("n", "rounds"):
        v = p.get(name)
        if isinstance(v, bool) or not isinstance(v, int) or v < (1 if name == "n" else 0):
            raise ValidationError(f"{name} must be an integer >= {1 if name == 'n' else 0}")
        limit = MAX_NODES if name == "n" else MAX_ROUNDS
        if v > limit:
            raise ValidationError(f"{name} must be <= {limit}")
    latency = _finite_number(p.get("latency_ms"), "latency_ms")
    bandwidth = _finite_number(p.get("bandwidth_MBps"), "bandwidth_MBps", minimum=0.000000000001)
    payload = _finite_number(p.get("payload_mb"), "payload_mb")
    return {"T1": t1, "f": serial, "n": p["n"], "rounds": p["rounds"],
            "latency_ms": latency, "bandwidth_MBps": bandwidth, "payload_mb": payload}


def compute_time(params: Any) -> dict[str, float | int]:
    p = validate_compute(params)
    n = p["n"]
    try:
        communication = 0.0 if n == 1 else p["rounds"] * (p["latency_ms"] / 1000.0 + p["payload_mb"] / p["bandwidth_MBps"])
        serial_bound = p["T1"] * (p["f"] + (1.0 - p["f"]) / n)
        time_s = serial_bound + communication
        speedup = p["T1"] / time_s
        efficiency = speedup / n
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValidationError("compute parameters produce an unrepresentable result") from exc
    values = (communication, serial_bound, time_s, speedup, efficiency)
    if not all(math.isfinite(v) for v in values):
        raise ValidationError("compute parameters produce a non-finite result")
    return {"time_s": time_s, "speedup": speedup, "efficiency": efficiency,
            "serial_bound_s": serial_bound, "communication_s": communication}


def load_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError(f"cannot read JSON from {path}: {exc}") from exc


def write_json(path: str | Path, data: Any) -> None:
    target = Path(path)
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot write JSON to {path}: {exc}") from exc


def _catalog(path: str | Path | None = None) -> dict[str, Any]:
    return load_json(path if path is not None else Path(__file__).parent.parent / "examples" / "catalog.json")


def demo(catalog_path: str | Path | None = None, fail_id: str = "sense-a") -> dict[str, Any]:
    raw_catalog = _catalog(catalog_path)
    modules, tasks = validate_catalog(raw_catalog)
    baseline = {m["id"]: m for m in modules}
    if fail_id not in baseline:
        raise ValidationError(f"unknown failure module id: {fail_id}")
    initial = [choose_modules(modules, task) for task in tasks]
    baseline[fail_id]["status"] = "fault"
    after_fault = [choose_modules(modules, task) for task in tasks]
    return {"model": "single-process capability and communication reference model",
            "scope": "assumed data; symbolic capability requests only; no navigation or other task execution, physical geometry, load, dynamics, or real distributed execution",
            "input": raw_catalog, "failure_module_id": fail_id,
            "initial": initial, "after_fault": after_fault,
            "communication_examples": communication_examples()}


def communication_examples() -> dict[str, Any]:
    base = {"T1": 10.0, "f": 0.02, "n": 8}
    cases = {
        "fast_network": {"rounds": 20, "payload_mb": 1, "bandwidth_MBps": 100, "latency_ms": 1},
        "slow_network": {"rounds": 20, "payload_mb": 1, "bandwidth_MBps": 5, "latency_ms": 20},
        "communication_heavy": {"rounds": 100, "payload_mb": 16, "bandwidth_MBps": 10, "latency_ms": 20},
    }
    out = {}
    for name, extra in cases.items():
        p = {**base, **extra}
        out[name] = {"parameters": p, **compute_time(p)}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prime_components",
        description="Modular component research: symbolic planning and local process experiments.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "compute"):
        child = sub.add_parser(command)
        child.add_argument("--output", required=True, help="path to output JSON")
        if command == "demo":
            child.add_argument("--catalog", help="catalog JSON path; defaults to examples/catalog.json")
            child.add_argument("--fail", default="sense-a", help="module id to mark fault; default: sense-a")
        else:
            child.add_argument("--input", help="single communication-parameter JSON object")
    portfolio_parser = sub.add_parser("portfolio", help="choose shared inventory for sequential symbolic tasks")
    portfolio_parser.add_argument("--input", default=str(Path(__file__).parent.parent / "examples" / "portfolio.json"))
    portfolio_parser.add_argument("--output", required=True)
    runtime_parser = sub.add_parser("runtime", help="compare real loopback worker processes with fault injection")
    runtime_parser.add_argument("--workers", type=int, default=3)
    runtime_parser.add_argument("--tasks", type=int, default=12)
    runtime_parser.add_argument("--iterations", type=int, default=20000)
    runtime_parser.add_argument("--timeout", type=float, default=30.0, help="whole-experiment deadline in seconds")
    runtime_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    exit_code = 0
    try:
        if args.command == "demo":
            result = demo(args.catalog, args.fail)
        elif args.command == "compute":
            result = {"model": "homogeneous-node communication estimate; assumed inputs",
                      "formula": "T_n=T1*(f+(1-f)/n)+rounds*(latency_ms/1000+payload_mb/bandwidth_MBps); n=1 communication=0",
                      "units": "payload and bandwidth use decimal MB; latency in ms; time in seconds",
                      "cases": communication_examples()}
            if args.input:
                supplied = load_json(args.input)
                result["input_case"] = {"parameters": validate_compute(supplied), **compute_time(supplied)}
        elif args.command == "portfolio":
            from .portfolio import choose_portfolio
            result = choose_portfolio(load_json(args.input))
            exit_code = 0 if result["feasible"] else 1
        else:
            from .runtime import run_experiment
            result = run_experiment(workers=args.workers, tasks=args.tasks,
                                    iterations=args.iterations, timeout_s=args.timeout)
            exit_code = 0 if result["all_correct"] else 1
        write_json(args.output, result)
    except ValidationError as exc:
        parser.error(str(exc))
    print(f"{args.command}: {'ok' if exit_code == 0 else 'not completed'}; report: {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
