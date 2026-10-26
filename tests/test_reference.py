import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prime_components import ValidationError, choose_modules, compute_time, validate_catalog


def catalog():
    return {"modules": [
        {"id": "a", "type": "sensor", "capabilities": ["vision", "map"], "interface": "x", "power_w": 1.0, "status": "ready"},
        {"id": "b", "type": "sensor", "capabilities": ["vision"], "interface": "x", "power_w": 1.0, "status": "ready"},
        {"id": "c", "type": "compute", "capabilities": ["map"], "interface": "x", "power_w": 1.0, "status": "ready"},
    ], "tasks": [{"id": "t", "need": {"vision": 1, "map": 1}, "interface": "x", "power_budget_w": 4.0}]}


class CatalogTests(unittest.TestCase):
    def test_invalid_ids_and_values_rejected(self):
        base = catalog()
        for mutate in (
            lambda x: x["modules"].append(copy.deepcopy(x["modules"][0])),
            lambda x: x["modules"][0].update(power_w=float("nan")),
            lambda x: x["modules"][0].update(power_w=float("inf")),
            lambda x: x["modules"][0].update(power_w=True),
            lambda x: x["modules"][0].update(status="broken"),
            lambda x: x["tasks"][0].update(need={}),
            lambda x: x["tasks"][0].update(need={"vision": True}),
            lambda x: x["tasks"][0].update(power_budget_w=-1),
        ):
            bad = copy.deepcopy(base)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_catalog(bad)

    def test_need_count_and_multicapability_counts_once_per_module(self):
        modules, tasks = validate_catalog(catalog())
        result = choose_modules(modules, tasks[0])
        self.assertEqual(result["selected"], ["a"])
        twice = copy.deepcopy(tasks[0])
        twice["need"] = {"vision": 2, "map": 1}
        self.assertEqual(choose_modules(modules, twice)["selected"], ["a", "b"])

    def test_type_priority_and_deterministic_id_tiebreak(self):
        modules, tasks = validate_catalog(catalog())
        task = {**tasks[0], "need": {"vision": 1, "map": 1}}
        self.assertEqual(choose_modules(modules, task)["selected"], ["a"])
        clones = [{**m, "id": "z" if m["id"] == "a" else "a" if m["id"] == "b" else m["id"]} for m in modules]
        # Equal one-type covers are ranked by power then lexicographic ID.
        self.assertEqual(choose_modules(clones, task)["selected"], ["z"])
        tied = [
            {"id": "z", "type": "combo", "capabilities": {"vision", "map"}, "interface": "x", "power_w": 1.0, "status": "ready"},
            {"id": "a", "type": "combo", "capabilities": {"vision", "map"}, "interface": "x", "power_w": 1.0, "status": "ready"},
        ]
        self.assertEqual(choose_modules(tied, task)["selected"], ["a"])

    def test_type_count_precedes_instance_count(self):
        modules = [
            {"id": "kit-a", "type": "kit", "capabilities": {"a"}, "interface": "x", "power_w": 1.0, "status": "ready"},
            {"id": "kit-b", "type": "kit", "capabilities": {"b"}, "interface": "x", "power_w": 1.0, "status": "ready"},
            {"id": "kit-c", "type": "kit", "capabilities": {"c"}, "interface": "x", "power_w": 1.0, "status": "ready"},
            {"id": "pair", "type": "pair", "capabilities": {"a", "b"}, "interface": "x", "power_w": 1.0, "status": "ready"},
            {"id": "extra", "type": "extra", "capabilities": {"c"}, "interface": "x", "power_w": 1.0, "status": "ready"},
        ]
        task = {"id": "types", "need": {"a": 1, "b": 1, "c": 1}, "interface": "x", "power_budget_w": 5}
        self.assertEqual(choose_modules(modules, task)["selected"], ["kit-a", "kit-b", "kit-c"])

    def test_duplicate_capability_within_one_module_counts_once(self):
        modules = [{"id": "one", "type": "sensor", "capabilities": {"vision"},
                    "interface": "x", "power_w": 1, "status": "ready"}]
        task = {"id": "twice", "need": {"vision": 2}, "interface": "x", "power_budget_w": 2}
        self.assertFalse(choose_modules(modules, task)["feasible"])

    def test_fault_replacement_and_no_backup(self):
        modules, tasks = validate_catalog(catalog())
        modules[0]["status"] = "fault"
        result = choose_modules(modules, tasks[0])
        self.assertEqual(result["selected"], ["b", "c"])
        modules[1]["status"] = "fault"
        self.assertFalse(choose_modules(modules, tasks[0])["feasible"])

    def test_interface_and_budget_block_feasibility(self):
        modules, tasks = validate_catalog(catalog())
        task = {**tasks[0], "interface": "other"}
        self.assertFalse(choose_modules(modules, task)["feasible"])

    def test_offline_and_size_limit(self):
        modules, tasks = validate_catalog(catalog())
        modules[0]["status"] = "offline"
        self.assertEqual(choose_modules(modules, tasks[0])["selected"], ["b", "c"])
        oversized = copy.deepcopy(catalog())
        oversized["modules"] *= 7
        with self.assertRaises(ValidationError):
            validate_catalog(oversized)
        task = {**tasks[0], "power_budget_w": 0.5}
        self.assertFalse(choose_modules(modules, task)["feasible"])


class ComputeTests(unittest.TestCase):
    def test_n_one_uses_serial_formula_and_zero_communication(self):
        result = compute_time({"T1": 10, "f": 0.2, "n": 1, "rounds": 99,
                               "latency_ms": 1, "payload_mb": 10, "bandwidth_MBps": 1})
        self.assertEqual(result["time_s"], 10)
        self.assertEqual(result["communication_s"], 0)
        self.assertEqual(result["speedup"], 1)

    def test_parallel_formula_and_network_counterexample(self):
        p = {"T1": 10, "f": 0.02, "n": 8, "rounds": 20,
             "latency_ms": 1, "payload_mb": 1, "bandwidth_MBps": 100}
        fast = compute_time(p)
        slow = compute_time({**p, "latency_ms": 20, "bandwidth_MBps": 5})
        self.assertAlmostEqual(fast["serial_bound_s"], 1.425)
        self.assertLess(fast["time_s"], 10)
        heavy = compute_time({**p, "rounds": 100, "payload_mb": 16,
                              "latency_ms": 20, "bandwidth_MBps": 10})
        self.assertLess(slow["speedup"], fast["speedup"])
        self.assertGreater(heavy["time_s"], 10)
        self.assertLess(heavy["speedup"], 1)
        self.assertGreater(slow["efficiency"], 0)

    def test_invalid_parallel_parameters(self):
        base = {"T1": 10, "f": 0.02, "n": 8, "rounds": 20,
                "latency_ms": 1, "payload_mb": 1, "bandwidth_MBps": 100}
        invalids = ({"n": True}, {"n": 0}, {"rounds": 1.2}, {"rounds": True},
                    {"f": 1.01}, {"f": float("nan")}, {"T1": float("inf")},
                    {"bandwidth_MBps": 0}, {"payload_mb": -1})
        for patch in invalids:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                compute_time({**base, **patch})

    def test_huge_integer_and_derived_overflow_rejected(self):
        huge = 10 ** 10000
        with self.assertRaises(ValidationError):
            validate_catalog({"modules": [{"id": "x", "type": "x", "capabilities": ["x"],
                                             "interface": "x", "power_w": huge, "status": "ready"}], "tasks": []})
        base = {"T1": 10, "f": 0.02, "n": 8, "rounds": 20,
                "latency_ms": 1, "payload_mb": 1, "bandwidth_MBps": 100}
        for patch in ({"n": 1_000_000_001}, {"rounds": 1_000_000_001},
                      {"payload_mb": 1e308, "bandwidth_MBps": 1e-12}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                compute_time({**base, **patch})


class CliTests(unittest.TestCase):
    def test_compute_cli_success_and_invalid_input_exit_two(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            good = {"T1": 10, "f": 0.02, "n": 8, "rounds": 20,
                    "latency_ms": 1, "payload_mb": 1, "bandwidth_MBps": 100}
            input_path = folder / "input.json"
            output_path = folder / "output.json"
            input_path.write_text(json.dumps(good), encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "prime_components", "compute",
                                  "--input", str(input_path), "--output", str(output_path)],
                                 cwd=project, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertAlmostEqual(json.loads(output_path.read_text(encoding="utf-8"))["input_case"]["time_s"], 1.645)
            input_path.write_text(json.dumps({**good, "n": True}), encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "prime_components", "compute",
                                  "--input", str(input_path), "--output", str(output_path)],
                                 cwd=project, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)


if __name__ == "__main__":
    unittest.main()
