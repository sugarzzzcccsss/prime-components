# Prime Components

[中文](README.md)

An open research project on modular intelligent components: reuse a small vocabulary of module types across a defined task set, coordinate edge computation, and recover from component failures.

“Prime” is a design metaphor, not a claim of unique factorization or universal minimality. We want to measure the tradeoffs among task coverage, the number of module types, performance, energy, and repair time.

## Status: v0.1.0 research seed

This repository contains original research notes and a dependency-free Python reference model. It does **not** contain a physical robot, a distributed runtime, neural inference, or evidence of data-center-equivalent performance.

The planner searches a small, supplied inventory for a single symbolic task. It checks capability counts, an interface label, availability, and a power budget. It does not validate geometry, mechanical loads, calibration, or safe operation. The failure example changes a status field and replans in one process; it does not measure physical repair time.

The compute example estimates latency under explicit homogeneous-node and communication assumptions. Its inputs are illustrative, not measured hardware specifications.

## Run

Python 3.10+, from the repository root; no third-party dependencies.

```sh
python -m unittest discover -s tests -v
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
```

## Research questions

- Can fewer module types cover a useful task set without unacceptable performance, energy, or cost penalties?
- When does sharing edge computation improve end-to-end performance over local execution?
- Does modular replacement reduce the elapsed time from failure to the next successful task?

See the Chinese [architecture draft](docs/architecture.md), [experiment protocol](docs/experiments.md), [prior work](docs/references.md), and [roadmap](docs/roadmap.md). English contributions are welcome. Report reproducible negative findings as well as positive ones.

Software and original documentation: [MIT](LICENSE). No hardware manufacturing files are provided. Linked third-party works retain their own terms.
