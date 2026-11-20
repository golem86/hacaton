# Suppression and differencing attack test report

**Scope:** synthetic helper and prototype route inventory only. No aggregate API exists, and no official aggregate was published. Parameter `k` is supplied per test and is not a production default.

## Results

| Attack/test | Result | What this proves |
| --- | --- | --- |
| Primary suppression for small category | PASS (helper) | A cell below synthetic `k` returns generic label and `count: null` |
| Complementary suppression | PASS (helper) | A companion cell is hidden when one visible cell plus total would expose the primary cell |
| Hidden count from total | PASS (one synthetic result) | In the covered vector, primary + companion are both hidden and no exact hidden count appears in group metadata |
| Small/intersection groups | PASS (helper) | Synthetic tiny categories/intersections are hidden without echoing their labels |
| Category differencing across separate queries | BLOCKED / no query surface | Six attack variants receive 404 because no aggregate route is registered; helper itself has no query-history protection |
| Cross-cycle differencing | BLOCKED / no query surface | No aggregate endpoint and no cross-cycle release ledger exists |
| Overlapping filters / repeated queries | BLOCKED / no query surface | No query endpoint is exposed. The stateless helper is not a defense if later exposed directly |
| Metadata/error leakage | PASS for tested nonexistent endpoint | 404 response does not echo synthetic category/filter values or counts |
| Dashboard/raw answers | PASS (route inventory only) | No prototype raw-answer, dashboard or participation route is registered |

Attack probes are implemented in `backend/tests/test_questionnaire_integration_prototype.py::test_aggregate_differencing_attack_surface_is_absent` for category, cross-cycle, overlapping-filter, repeated-query, intersection and total-recovery paths. They verify **absence of an endpoint**, not that future aggregates are safe.

The helper `suppress_cells()` is only a one-shot synthetic demonstration. It cannot protect against overlapping or repeated queries, arbitrary combinations, temporal differencing, or query metadata side channels. Before any aggregate endpoint: approve a conservative release ledger/query budget (or a reviewed statistical privacy mechanism), stable population semantics, closed set of cuts, primary/complementary suppression, total handling, and cross-cycle policy. Re-test with synthetic attack suites before enabling.

## Exact current commands

`..\audit-venv\Scripts\python.exe -m pytest backend/tests/test_questionnaire_integration_prototype.py -q -rs` from the repository root. Targeted results: **40 passed, 1 skipped**; the skip is only the OS-denied symbolic-link creation case. All six differencing/overlap/repeat routes returned generic 404. No official data or production `k` was used.
