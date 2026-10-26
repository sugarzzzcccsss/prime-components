import time
import unittest
import hashlib
import json
import threading
import urllib.error
import urllib.request

from prime_components.core import ValidationError
from prime_components.runtime import CoordinatorState, _QuietHTTPServer, _make_handler, run_experiment
from prime_components.worker import calculate_digest


class WorkerProtocolTests(unittest.TestCase):
    def test_claim_fencing_owner_and_duplicate_acceptance(self):
        task = {"task_id": "task-0000", "seed": "0" * 64, "iterations": 2}
        digest = calculate_digest(task["seed"], task["iterations"])
        state = CoordinatorState([task], {task["task_id"]: digest})
        owner = "a" * 32
        other = "b" * 32
        state.register_worker(owner)
        state.register_worker(other)
        state.hello(owner)
        state.hello(other)
        state.release_pool()
        job = state.claim(owner)["job"]

        self.assertEqual(state.accept_result(task["task_id"], other, job["attempt"],
                                             job["fencing_token"], digest), (False, "wrong_worker"))
        self.assertEqual(state.accept_result(task["task_id"], owner, job["attempt"],
                                             "0" * 32, digest), (False, "stale_fencing_token"))
        self.assertEqual(state.accept_result(task["task_id"], owner, True,
                                             job["fencing_token"], digest), (False, "invalid_attempt"))
        self.assertEqual(state.accept_result(task["task_id"], owner, job["attempt"],
                                             job["fencing_token"], "invalid"), (False, "invalid_digest"))
        self.assertEqual(state.accept_result(task["task_id"], owner, job["attempt"],
                                             job["fencing_token"], digest), (True, "accepted"))
        self.assertEqual(state.accept_result(task["task_id"], owner, job["attempt"],
                                             job["fencing_token"], digest), (False, "task_not_leased"))

    def test_old_attempt_is_rejected_after_reassignment_and_bad_digest(self):
        task = {"task_id": "task-0000", "seed": "0" * 64, "iterations": 1}
        digest = calculate_digest(task["seed"], task["iterations"])
        state = CoordinatorState([task], {task["task_id"]: digest})
        old_owner, new_owner = "a" * 32, "b" * 32
        state.register_worker(old_owner)
        state.register_worker(new_owner)
        state.hello(old_owner)
        state.hello(new_owner)
        state.release_pool()
        old_job = state.claim(old_owner)["job"]
        state.worker_exited(old_owner)
        new_job = state.claim(new_owner)["job"]
        self.assertEqual(new_job["attempt"], 2)
        self.assertEqual(state.accept_result(task["task_id"], new_owner, old_job["attempt"],
                                             old_job["fencing_token"], digest), (False, "stale_fencing_token"))
        self.assertEqual(state.accept_result(task["task_id"], new_owner, new_job["attempt"],
                                             new_job["fencing_token"], "f" * 64), (False, "digest_mismatch"))

    def test_http_readiness_invalid_body_and_token(self):
        task = {"task_id": "task-0000", "seed": "0" * 64, "iterations": 1}
        session, token = "a" * 32, "b" * 64
        state = CoordinatorState([task])
        state.register_worker(session)
        server = _QuietHTTPServer(("127.0.0.1", 0), _make_handler(state, token))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            headers = {"X-Worker-Session": session, "X-Experiment-Token": token}
            hello = opener.open(urllib.request.Request(base + "/hello", headers=headers), timeout=1)
            self.assertTrue(json.loads(hello.read())["hello"])
            state.release_pool()
            gate = opener.open(urllib.request.Request(base + "/gate", headers=headers), timeout=1)
            self.assertTrue(json.loads(gate.read())["released"])
            bad = urllib.request.Request(base + "/hello", headers={"X-Worker-Session": session,
                                                                      "X-Experiment-Token": "0" * 64})
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(bad, timeout=1)
            self.assertEqual(error.exception.code, 403)
            malformed = urllib.request.Request(base + "/result", data=b"{", headers=headers,
                                               method="POST")
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(malformed, timeout=3)
            self.assertEqual(error.exception.code, 400)
        finally:
            state.begin_shutdown()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            calculate_digest("nope", 1)
        with self.assertRaises(ValueError):
            calculate_digest("0" * 64, True)
        expected = hashlib.sha256(bytes.fromhex("0" * 64) + (0).to_bytes(4, "big")).hexdigest()
        self.assertEqual(calculate_digest("0" * 64, 1), expected)
        self.assertEqual(calculate_digest("0" * 64, 0), "0" * 64)
        with self.assertRaises(ValidationError):
            run_experiment(workers=True)
        with self.assertRaises(ValidationError):
            run_experiment(tasks=100, iterations=100_000)
        with self.assertRaises(ValidationError):
            run_experiment(workers=1, inject_failure=True)


class RuntimeExperimentTests(unittest.TestCase):
    def test_real_workers_and_fault_recovery_match_single_worker(self):
        report = run_experiment(workers=3, tasks=1, iterations=25, timeout_s=12.0)
        self.assertTrue(report["all_correct"], report)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(set(report["scenarios"]),
                         {"single_worker", "multi_worker", "multi_worker_failure"})
        for scenario in report["scenarios"].values():
            self.assertTrue(scenario["matches_single_worker"])
            self.assertTrue(scenario["correct_against_oracle"])
            self.assertEqual(scenario["workers_started"], scenario["workers"])
            self.assertEqual(scenario["workers_hello_ready"], scenario["workers"])
            self.assertTrue(scenario["cleanup"]["all_workers_stopped"])
            self.assertTrue(scenario["cleanup"]["server_thread_stopped"])
            self.assertEqual(len(scenario["task_results"]), 1)
            self.assertRegex(scenario["task_results"]["task-0000"]["digest"], r"^[0-9a-f]{64}$")
            self.assertEqual([event["seq"] for event in scenario["events"]],
                             list(range(1, len(scenario["events"]) + 1)))
            self.assertEqual(sorted(event["t_rel_s"] for event in scenario["events"]),
                             [event["t_rel_s"] for event in scenario["events"]])
        failed = report["scenarios"]["multi_worker_failure"]
        self.assertIn("worker-0000", failed["workers_claimed"])
        self.assertNotIn("worker-0000", failed["workers_completed"])
        names = [event["event"] for event in failed["events"]]
        self.assertIn("failure_worker_at_precompute_barrier", names)
        self.assertIn("failure_injection_requested", names)
        self.assertIn("worker_process_exit_confirmed", names)
        self.assertIn("lease_reclaimed_after_confirmed_process_exit", names)
        self.assertTrue(all("session" not in event and "token" not in event for event in failed["events"]))
        self.assertTrue(any(event.get("attempt", 0) >= 2 and event["event"] == "result_accepted"
                            for event in failed["events"]))
        self.assertIsNotNone(failed["failure_to_first_retry_success_s"])
        self.assertIsNotNone(failed["failure_to_all_complete_s"])
        self.assertIn("python", report["environment"])
        self.assertIn("os", report["environment"])
        self.assertIn("cpu_count", report["environment"])
        self.assertNotIn("token", repr(report).lower())

    def test_all_workers_failed_returns_finite_report(self):
        started = time.monotonic()
        report = run_experiment(workers=2, tasks=1, iterations=1, timeout_s=5.0,
                                fail_all_workers=True)
        elapsed = time.monotonic() - started
        self.assertFalse(report["all_correct"])
        fault = report["scenarios"]["multi_worker_failure"]
        self.assertEqual(fault["status"], "failed")
        self.assertEqual(fault["reason"], "no_live_workers_after_injected_failure")
        self.assertEqual(fault["workers_started"], 2)
        self.assertEqual(fault["workers_hello_ready"], 2)
        self.assertNotIn("task-0000", fault["results"])
        self.assertTrue(fault["cleanup"]["all_workers_stopped"])
        self.assertIsNotNone(fault["wall_s"])
        self.assertLess(elapsed, 15.0)

    def test_short_shared_deadline_returns_finite_timeout_report(self):
        started = time.monotonic()
        report = run_experiment(workers=2, tasks=2, iterations=1, timeout_s=0.0001)
        self.assertFalse(report["all_correct"])
        self.assertEqual(report["status"], "timed_out")
        self.assertLess(time.monotonic() - started, 3.0)


if __name__ == "__main__":
    unittest.main()
