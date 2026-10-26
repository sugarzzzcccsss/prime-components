"""Exact finite-inventory planner for sequential symbolic tasks.

The search minimizes the shared ready inventory under the supplied symbolic
capability, interface, and per-task power-budget constraints. It does not
model simultaneous execution or physical compatibility.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .core import ValidationError, choose_modules, validate_catalog

MAX_PORTFOLIO_MODULES = 16
MAX_PORTFOLIO_TASKS = 32
MODEL = "finite-inventory sequential symbolic portfolio planner"
SCOPE = (
    "exact enumeration under the supplied finite inventory and symbolic capability, "
    "interface, and per-task power constraints; tasks execute sequentially and may "
    "reuse instances; no geometry, physical compatibility, or global-world minimum is proven"
)


def choose_portfolio(data: Any) -> dict[str, Any]:
    """Choose the lowest-ranked shared ready inventory feasible for all tasks.

    Tasks are checked independently and execute sequentially, so the same
    selected module instance may be reused by different task plans. Empty task
    lists are rejected because they have no meaningful minimum portfolio.
    """
    modules, tasks = validate_catalog(data)
    if len(modules) > MAX_PORTFOLIO_MODULES:
        raise ValidationError(
            f"portfolio planning supports at most {MAX_PORTFOLIO_MODULES} total modules"
        )
    if not tasks:
        raise ValidationError("portfolio planning requires at least one task")
    if len(tasks) > MAX_PORTFOLIO_TASKS:
        raise ValidationError(
            f"portfolio planning supports at most {MAX_PORTFOLIO_TASKS} tasks"
        )

    # A type label denotes one nominal specification in this model. Status and
    # instance ID vary by instance; capabilities, interface, and power do not.
    type_specs: dict[str, tuple[frozenset[str], str, float]] = {}
    for module in modules:
        spec = (frozenset(module["capabilities"]), module["interface"], module["power_w"])
        previous = type_specs.setdefault(module["type"], spec)
        if previous != spec:
            raise ValidationError(
                f"inconsistent nominal specification for module type: {module['type']}"
            )

    individual_plans = [choose_modules(modules, task) for task in tasks]
    modules_by_id = {module["id"]: module for module in modules}
    individual_ids = sorted({
        module_id
        for plan in individual_plans if plan["feasible"]
        for module_id in plan["selected"]
    })
    individual_modules = [modules_by_id[module_id] for module_id in individual_ids]
    individual_power = sum(module["power_w"] for module in individual_modules)
    if not math.isfinite(individual_power):
        raise ValidationError("individual inventory power sum is not finite")
    individual_inventory = {
        "selected": individual_ids,
        "types": sorted({module["type"] for module in individual_modules}),
        "power_w": individual_power,
    }
    result_context = {"model": MODEL, "scope": SCOPE, "input": copy.deepcopy(data),
                      "individual_plans": individual_plans,
                      "individual_inventory": individual_inventory}

    ready = [module for module in modules if module["status"] == "ready"]
    count = len(ready)
    subset_count = 1 << count
    all_masks = range(subset_count)

    # For each task, calculate feasibility for every exact subset directly in
    # O(N * 2^N), then compute its upward closure in O(N * 2^N). Calling the
    # exhaustive single-task chooser for every candidate would add a 3^N
    # inner search, so choose_modules is reserved for the final plans.
    feasible_subsets: list[list[bool]] = []
    for task in tasks:
        feasible = [False] * subset_count
        for mask in all_masks:
            power = 0.0
            capability_counts: dict[str, int] = {}
            compatible = True
            for i, module in enumerate(ready):
                if not mask & (1 << i):
                    continue
                if module["interface"] != task["interface"]:
                    compatible = False
                    break
                power += module["power_w"]
                for capability in module["capabilities"]:
                    capability_counts[capability] = capability_counts.get(capability, 0) + 1
            feasible[mask] = (
                compatible
                and power <= task["power_budget_w"]
                and all(capability_counts.get(capability, 0) >= needed
                        for capability, needed in task["need"].items())
            )
        has_feasible_subinventory = feasible[:]
        for bit in range(count):
            bit_mask = 1 << bit
            for mask in all_masks:
                if mask & bit_mask:
                    has_feasible_subinventory[mask] |= has_feasible_subinventory[mask ^ bit_mask]
        feasible_subsets.append(has_feasible_subinventory)

    best_rank: tuple[int, int, float, tuple[str, ...]] | None = None
    best_mask: int | None = None
    for mask in all_masks:
        if not all(task_feasible[mask] for task_feasible in feasible_subsets):
            continue
        selected = [ready[i] for i in range(count) if mask & (1 << i)]
        ids = tuple(sorted(module["id"] for module in selected))
        power = sum(module["power_w"] for module in selected)
        if not math.isfinite(power):
            raise ValidationError("portfolio inventory power sum is not finite")
        rank = (len({module["type"] for module in selected}), len(selected), power, ids)
        if best_rank is None or rank < best_rank:
            best_rank, best_mask = rank, mask

    if best_mask is None:
        return {**result_context,
            "feasible": False,
            "selected": [],
            "types": [],
            "inventory_power_w": 0.0,
            "task_plans": [],
            "objective": None,
        }

    selected = [ready[i] for i in range(count) if best_mask & (1 << i)]
    selected.sort(key=lambda module: module["id"])
    task_plans = [choose_modules(selected, task) for task in tasks]
    return {**result_context,
        "feasible": True,
        "selected": [module["id"] for module in selected],
        "types": sorted({module["type"] for module in selected}),
        "inventory_power_w": sum(module["power_w"] for module in selected),
        "task_plans": task_plans,
        "objective": {
            "type_count": best_rank[0],
            "instance_count": best_rank[1],
            "inventory_power_w": best_rank[2],
            "ids": list(best_rank[3]),
        },
    }
