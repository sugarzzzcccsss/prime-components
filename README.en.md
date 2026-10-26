# Prime Components

[中文](README.md)

An open research project on modular intelligent components: reuse a small vocabulary of module types across a defined task set, coordinate edge computation, and recover from component failures.

“Prime” is a design metaphor, not a claim of unique factorization or universal minimality. We want to measure the tradeoffs among task coverage, the number of module types, performance, energy, and repair time.

## Status: v0.2.0 local process experiments

This repository now runs separate Python workers that exchange JSON over loopback HTTP, execute deterministic SHA-256 tasks, and recover an in-flight task after a worker is terminated. A single coordinator is the explicit baseline. No physical robot, multi-device inference, decentralized consensus, or data-center-equivalent performance has been demonstrated.

The new portfolio planner selects shared inventory for a set of sequential symbolic tasks. It checks capability counts, interface labels, nominal type consistency, availability, and per-task power budgets. It does not validate geometry, mechanical loads, calibration, or safe operation. The original single-task model remains available.

The `compute` command remains a formula with illustrative inputs. The `runtime` command measures real local process execution; all workers still share one machine. Its fault-recovery measurements are not physical repair times or cluster benchmarks.

## Run

Python 3.10+, from the repository root; no third-party dependencies.

```sh
python -m unittest discover -s tests -v
python -m prime_components runtime --output results/runtime.json
python -m prime_components portfolio --output results/portfolio.json
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
```

`runtime` compares one worker, multiple healthy workers, and multiple workers with a failure. Reports include task results and event traces. `portfolio` compares shared-inventory planning against independently optimized tasks. Exit status is 0 for success, 1 for an infeasible or unsuccessful experiment, and 2 for invalid input. Reports for valid unsuccessful experiments are preserved.

## Research questions

- Can fewer module types cover a useful task set without unacceptable performance, energy, or cost penalties?
- When does sharing edge computation improve end-to-end performance over local execution?
- Does modular replacement reduce the elapsed time from failure to the next successful task?

See the Chinese [runtime guide](docs/runtime.md), [portfolio guide](docs/portfolio.md), [experiment protocol](docs/experiments.md), [prior work](docs/references.md), and [roadmap](docs/roadmap.md). English contributions are welcome. Report reproducible negative findings as well as positive ones.

Software and original documentation: [MIT](LICENSE). No hardware manufacturing files are provided. Linked third-party works retain their own terms.
