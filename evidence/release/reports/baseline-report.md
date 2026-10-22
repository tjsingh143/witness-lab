# Witness clean-baseline report

Generated 2026-10-22T02:48:57.076Z from the SQLite results database only (no hand-entered results).

Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.

## 6. Clean baselines (brief 7.3)

### 6a. Baseline runs started on freshly restored golden clones (provenance recorded by the runner)

_none_

Independent fresh-clone trials counted (first fair baseline per distinct restore): **0** -> runs none.

### 6c. All fair baseline runs (long-lived and fresh VMs): 2

| case_id | device | runs | passes | observed | retried | lat_min_ms | lat_median_ms | lat_max_ms |
|---|---|---|---|---|---|---|---|---|
| C-ENVIRONMENT | (run) | 2 | 2 | - | 0 |  |  |  |
| C-GATEWAY | dev-a | 2 | 2 | PASS | 0 |  |  |  |
| C-GATEWAY | dev-b | 2 | 2 | PASS | 0 |  |  |  |
| C-HEALTH | dev-a | 2 | 2 | PASS | 0 | 0.8 | 0.8 | 0.8 |
| C-HEALTH | dev-b | 2 | 2 | PASS | 0 | 1.0 | 1.1 | 1.2 |
| C-IDENTIFY | dev-a | 2 | 2 | PASS | 0 | 0.9 | 1.2 | 1.5 |
| C-IDENTIFY | dev-b | 2 | 2 | PASS | 0 | 1.0 | 1.2 | 1.3 |
| C-READ-CLOCK | dev-a | 2 | 2 | PASS | 0 | 0.9 | 1.2 | 1.4 |
| C-READ-CLOCK | dev-b | 2 | 2 | PASS | 0 | 0.9 | 1.1 | 1.2 |
| C-READ-SERIES | dev-a | 2 | 2 | PASS | 0 | 0.8 | 0.8 | 0.8 |
| C-READ-SERIES | dev-b | 2 | 2 | PASS | 0 | 0.8 | 0.9 | 1.0 |
