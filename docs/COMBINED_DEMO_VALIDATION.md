# Combined preview verification — 2026-10-01

Base commit: `068b85a`. Branch: `codex/combined-demo`. Local FastAPI preview on port 8012. No backend/schema changes.

## Automated checks

- `node --test tests/combined-demo.test.mjs`: four passing tests for average speed, cap violation, expired window, invalid inputs and holding instead of a crawl-speed recommendation.
- Node syntax checks: app.js, engine.js, scene.js, workspace.js, locales.js and approach.mjs.
- `python -m pytest services/ai/tests -q`: **38 passed, 1 failed**, 13.52 s. Existing `test_canonical_demo_state_and_topology_routes` submits seed `20261001`, but `/api/v2/state` caps seed at `999999`, returning 422. Both values verified in unchanged `git show HEAD` baseline. This failure was not introduced or hidden by the frontend branch.
- Impeccable detector on frontend/index.html returned no findings but could not resolve FastAPI's absolute stylesheet routes to disk; this is a limited HTML scan, not full CSS certification.
- Independent source review found and corrected stale train capture in forecasts, reversed southbound map positions and SSE reconnect clock rollback. Final review reported no unresolved critical/important source issue.

## Browser and runtime checks

- Desktop: Kazakhstan map and actual Three.js station render with SIM trains, station building, rails, camera controls and arrival board. Proof: `demo-preview/station.jpg`.
- Narrow viewport 390 × 844: scenario/speed, game and dispatcher pages stay inside viewport; diagrams/tables scroll locally. No page-wide overflow observed.
- Scenario: default 4 km / 12 minute approach calculates 20 km/h. Input 50 km marks the same window unreachable and removes the recommendation.
- Game: completed all four B decisions. Delay carries between stages; final cost 1059 versus baseline 1668, best 850 and score 80/100. These are computed training-game outputs, not backend optimizer or real-world performance evidence.
- API workspace: 28 rows, one-hertz stream, pause, current clock, train selection and keyboard Tab focus. Train register DOM remains stable during updates.
- Advisory request returned captured time and known wait 0.0 min, with unvalidated Kazakhstan ML and heuristic boundaries visible. No fabricated ML values.
- Actual planner at captured 11:00:09: pair SIM-KOK_AST-F01 / SIM-KOK_AST-R01 `OPTIMAL`, validator passed; full 28 plan `INFEASIBLE`, displayed separately.
- History: Home returns to the first snapshot, 11:00:00. Planner on that recorded state uses its saved incident context.
- CSV downloaded to the user's Downloads: 1288 records, five expected columns, SIM IDs. Browser automation download event timed out, so file existence and contents were verified independently on disk.
- RU/KK and light/dark: model page shows actual `pkp-main-298694c` and `kz-synthetic-schedule-v1`, plus the unreviewed Kazakh notice.
- API outage: stopped only this preview's verified uvicorn process. Last snapshot froze at 11:00:29, 28 rows stayed visible, error/retry appeared. Restart resumed beyond 11:00:29 without resetting and hid the connection error.
- No console errors observed before the deliberate API outage; connection errors during that outage are expected.

## Explicit limits

WebGL initialization fallback and disposal were source-reviewed; GPU loss/no-WebGL was not forced in this browser. Kazakh has not been reviewed by a native speaker. No frame-rate/performance certification, operational train-control claim or end-to-end execution of a 28-train optimized plan. Reference game/map and backend snapshot remain distinct states.
