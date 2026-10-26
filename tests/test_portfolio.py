import copy
import itertools
import random
import unittest

from prime_components import ValidationError, choose_modules, validate_catalog
from prime_components.portfolio import MAX_PORTFOLIO_MODULES, MAX_PORTFOLIO_TASKS, choose_portfolio


def task(task_id, need, interface="bus-v1", budget=10.0):
    return {"id": task_id, "need": need, "interface": interface, "power_budget_w": budget}


def module(mid, kind, caps, power=1.0, interface="bus-v1", status="ready"):
    return {"id": mid, "type": kind, "capabilities": caps,
            "interface": interface, "power_w": power, "status": status}


class PortfolioTests(unittest.TestCase):
    def test_joint_inventory_prefers_one_shared_type_over_individual_optima(self):
        data = {
            "modules": [
                module("vision-a", "vision", ["inspect"], 1.0),
                module("vision-b", "vision", ["inspect"], 1.0),
                module("motion-a", "motion", ["move"], 1.0),
                module("shared-a", "shared", ["inspect", "move"], 1.5),
                module("shared-b", "shared", ["inspect", "move"], 1.5),
                module("universal", "universal", ["inspect", "move"], 5.0),
            ],
            "tasks": [task("inspect", {"inspect": 2}, budget=3),
                      task("move", {"move": 1}, budget=2)],
        }
        modules, tasks = validate_catalog(data)
        individual_plans = [choose_modules(modules, item) for item in tasks]
        self.assertEqual([plan["selected"] for plan in individual_plans],
                         [["vision-a", "vision-b"], ["motion-a"]])
        result = choose_portfolio(data)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["selected"], ["shared-a", "shared-b"])
        self.assertEqual(result["types"], ["shared"])
        self.assertEqual(result["objective"]["type_count"], 1)
        self.assertEqual([p["selected"] for p in result["task_plans"]],
                         [["shared-a", "shared-b"], ["shared-a"]])
        self.assertEqual(result["individual_inventory"], {
            "selected": ["motion-a", "vision-a", "vision-b"],
            "types": ["motion", "vision"],
            "power_w": 3.0,
        })

    def test_inconsistent_nominal_specification_for_one_type_is_rejected(self):
        base = {"modules": [module("a", "shared", ["a"]), module("b", "shared", ["a"])],
                "tasks": [task("a-task", {"a": 1})]}
        for changes in ({"capabilities": ["b"]}, {"interface": "other"}, {"power_w": 2.0}):
            data = copy.deepcopy(base)
            data["modules"][1].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    ValidationError, "inconsistent nominal specification"):
                choose_portfolio(data)
        base["modules"][1]["status"] = "fault"
        self.assertTrue(choose_portfolio(base)["feasible"])

    def test_interfaces_budget_and_status_are_respected(self):
        data = {"modules": [
            module("wrong-interface", "wrong-interface", ["x"], interface="other"),
            module("too-expensive", "too-expensive", ["x"], power=5),
            module("offline", "offline", ["x"], status="offline"),
            module("fault", "fault", ["x"], status="fault"),
        ], "tasks": [task("x-task", {"x": 1}, budget=2)]}
        result = choose_portfolio(data)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["task_plans"], [])
        self.assertIsNone(result["objective"])
        self.assertEqual(len(result["individual_plans"]), 1)
        self.assertEqual(result["input"], data)
        self.assertTrue(result["scope"])

    def test_multi_capability_is_symbolic_and_does_not_claim_concurrency(self):
        data = {"modules": [module("combo", "combo", ["a", "b"])],
                "tasks": [task("a", {"a": 1}), task("b", {"b": 1})]}
        result = choose_portfolio(data)
        self.assertEqual(result["selected"], ["combo"])
        self.assertEqual([plan["selected"] for plan in result["task_plans"]],
                         [["combo"], ["combo"]])

    def test_empty_tasks_duplicate_ids_and_size_limit(self):
        with self.assertRaises(ValidationError):
            choose_portfolio({"modules": [], "tasks": []})
        with self.assertRaises(ValidationError):
            choose_portfolio({"modules": [module("x", "x", ["x"])],
                              "tasks": [task("same", {"x": 1}), task("same", {"x": 1})]})
        too_many = {"modules": [module(f"m{i}", "x", ["x"]) for i in range(MAX_PORTFOLIO_MODULES + 1)],
                    "tasks": [task("x", {"x": 1})]}
        with self.assertRaisesRegex(ValidationError, "at most 16"):
            choose_portfolio(too_many)
        too_many_tasks = {"modules": [module("x", "x", ["x"])],
                          "tasks": [task(f"t{i}", {"x": 1}) for i in range(MAX_PORTFOLIO_TASKS + 1)]}
        with self.assertRaisesRegex(ValidationError, "at most 32"):
            choose_portfolio(too_many_tasks)

    def test_deterministic_ids_and_input_not_mutated(self):
        data = {"modules": [module("z", "same", ["x"]), module("a", "same", ["x"])],
                "tasks": [task("x", {"x": 1})]}
        before = copy.deepcopy(data)
        self.assertEqual(choose_portfolio(data)["selected"], ["a"])
        self.assertEqual(data, before)

    def test_matches_independent_inventory_enumeration_oracle(self):
        rng = random.Random(20261026)
        cases = [
            {
                "modules": [module("double-a0", "double-a", ["a"], power=1),
                            module("double-a1", "double-a", ["a"], power=1)],
                "tasks": [task("need-two-a", {"a": 2}, budget=2)],
            },
            {
                "modules": [module("only-a", "a", ["a"])],
                "tasks": [task("need-two-a", {"a": 2})],
            },
        ]
        observed_need_sizes = set()
        observed_interfaces = set()
        observed_budgets = set()

        feasible_cases = 0
        infeasible_cases = 0
        multi_instance_optima = 0
        for case in range(24):
            modules_data = []
            for kind in ("A", "B", "C", "D"):
                caps = [cap for cap in ("a", "b", "c") if rng.random() < 0.5]
                if not caps:
                    caps = [rng.choice(("a", "b", "c"))]
                power = float(rng.randint(1, 4))
                interface = rng.choice(("bus-v1", "bus-v2"))
                for instance in range(rng.randint(1, 2)):
                    modules_data.append(module(
                        f"{kind.lower()}-{instance}", kind, caps,
                        power=power, interface=interface,
                        status=rng.choice(("ready", "ready", "fault", "offline")),
                    ))
            tasks_data = []
            for task_index in range(rng.randint(1, 3)):
                requested_caps = rng.sample(("a", "b", "c"), rng.randint(1, 2))
                needs = {cap: rng.randint(1, 2) for cap in requested_caps}
                interface = rng.choice(("bus-v1", "bus-v2"))
                budget = float(rng.randint(1, 8))
                tasks_data.append(task(f"random-{case}-task-{task_index}", needs,
                                       interface=interface, budget=budget))
                observed_need_sizes.add(len(needs))
                observed_interfaces.add(interface)
                observed_budgets.add(budget)
            cases.append({"modules": modules_data, "tasks": tasks_data})

        for case_index, data in enumerate(cases):
            modules, tasks = validate_catalog(data)
            ready = [m for m in modules if m["status"] == "ready"]
            oracle = None
            for size in range(len(ready) + 1):
                for subset in itertools.combinations(ready, size):
                    plans = [choose_modules(list(subset), t) for t in tasks]
                    if not all(plan["feasible"] for plan in plans):
                        continue
                    ids = tuple(sorted(m["id"] for m in subset))
                    rank = (len({m["type"] for m in subset}), len(subset),
                            sum(m["power_w"] for m in subset), ids)
                    if oracle is None or rank < oracle[0]:
                        oracle = (rank, list(ids))
            actual = choose_portfolio(data)
            self.assertEqual(actual["feasible"], oracle is not None, f"case {case_index}")
            if oracle:
                feasible_cases += 1
                if actual["objective"]["instance_count"] >= 2:
                    multi_instance_optima += 1
                self.assertEqual(actual["selected"], oracle[1], f"case {case_index}")
            else:
                infeasible_cases += 1
        self.assertGreater(feasible_cases, 0)
        self.assertGreater(infeasible_cases, 0)
        self.assertGreater(multi_instance_optima, 0)
        self.assertEqual(observed_need_sizes, {1, 2})
        self.assertEqual(observed_interfaces, {"bus-v1", "bus-v2"})
        self.assertGreater(len(observed_budgets), 1)

    def test_non_finite_individual_inventory_power_is_rejected(self):
        data = {
            "modules": [module("huge-a", "type-a", ["a"], power=1e308),
                        module("huge-b", "type-b", ["b"], power=1e308)],
            "tasks": [task("a-task", {"a": 1}, budget=1e308),
                      task("b-task", {"b": 1}, budget=1e308)],
        }
        with self.assertRaisesRegex(ValidationError, "individual inventory power sum is not finite"):
            choose_portfolio(data)


if __name__ == "__main__":
    unittest.main()
