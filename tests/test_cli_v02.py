import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V02CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "prime_components", *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=45)

    def test_portfolio_success_and_infeasible_report(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output = folder / "plan.json"
            completed = self.run_cli("portfolio", "--output", str(output))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["selected"], ["shared-a", "shared-b"])
            invalid_inventory = folder / "empty.json"
            # A UTF-8 BOM is a common Windows editor output and remains readable.
            invalid_inventory.write_text(json.dumps({"modules": [], "tasks": [
                {"id": "requires-camera", "need": {"camera": 1},
                 "interface": "bus-v1", "power_budget_w": 10}]}), encoding="utf-8-sig")
            failed = self.run_cli("portfolio", "--input", str(invalid_inventory), "--output", str(output))
            self.assertEqual(failed.returncode, 1, failed.stderr)
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["feasible"])

    def test_runtime_cli_result_and_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime.json"
            completed = self.run_cli("runtime", "--workers", "2", "--tasks", "3",
                                     "--iterations", "50", "--timeout", "30", "--output", str(output))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["all_correct"])
            rejected = self.run_cli("runtime", "--timeout", "nan", "--output", str(output))
            self.assertEqual(rejected.returncode, 2)
            self.assertNotIn("Traceback", rejected.stderr)

    def test_bad_encoding_and_output_path_report_input_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "bad.json"
            source.write_bytes(b"\xff\x00\x81")
            completed = self.run_cli("portfolio", "--input", str(source), "--output", str(folder / "out.json"))
            self.assertEqual(completed.returncode, 2)
            self.assertNotIn("Traceback", completed.stderr)
            completed = self.run_cli("compute", "--output", str(folder))
            self.assertEqual(completed.returncode, 2)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
