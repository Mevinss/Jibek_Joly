# Realtime demo verification — 2026-10-01

Branch: `codex/combined-demo`. Repair base: `a190bcc`. Local FastAPI preview: port 8012.

## Automated checks

- `python -m pytest services/ai/tests -q`: **39 passed**, 12.83 s, one Starlette/httpx deprecation warning. The existing canonical-state test was reproduced failing with 422 for seed `20261001`; the endpoint now accepts a nonnegative signed-32-bit seed. HTTP smoke check after restarting the preview returned 200 with the same seed.
- `node --test tests/combined-demo.test.mjs tests/realtime-demo.test.mjs`: **11 passed**. Seven realtime tests cover ISO/numeric UTC+5 clocks, separate station axes, history vs timetable, nine stations, reverse routes, terminal arrival at current speed, station dwell, speed restrictions/closure/unreachable timing, stale/duplicate/malformed frames and explicit reset.
- Regression test for a train at 260 km travelling 60 km/h to AST at 269 km failed before the continuation fix and passes after it: arrival at 540 seconds, then a stationary segment.
- Node syntax checks through `node --input-type=module --check` passed for app.js, realtime.js and scene.js. The older local Node binary does not support `--experimental-default-type=module`; stdin module checks were used instead.
- RU/KK locale key sets match. No literal interface translation keys are missing.
- Contract export ran successfully; generated files have no semantic changes.
- Independent source review identified and corrected replay/context mixing, stale closure rendering in 3D, hash navigation, distorted terminal continuation and partial-initialization retry. Closed stream callbacks are excluded during snapshot refresh.
- Impeccable CSS scan: off-ramp literal text sizes aligned to the documented 12/14/16/20/28 px ramp. The Inter-font warning is retained because the established project brief explicitly preserves Inter. This scan is not performance certification.

## Browser checks

- All nine `main` station names visible; 28 SIM train rows from API. Whole-corridor diagram displays nine station rows. North and south selection filters the diagram/map.
- Train combo, diagram Enter selection, map and station selection work. Actual Three.js canvas displays trains with SIM identifiers from the same snapshot. Camera controls remain available.
- SSE advances once per real second; ×10 changes virtual tempo. History contains actual received coordinates. No optimized-plan or ML substitution.
- Closure at 11:00:23 reduced the actual demo index from 93.1 to 57.1. Selected affected train displayed no speed and the hold/closure explanation.
- Replay returned to 11:00:00. Changing an incident restored the latest 11:04:06 snapshot before injection and retained pause, preventing backward/mixed future history.
- RU/KK and theme changes preserved snapshot 11:04:06 and 48 stored rows. Kazakh notice remains unreviewed.
- Brand link switched 3D to map; browser Back restored the selected station's 3D view.
- Real CP-SAT pair plan passed validation and showed 11 block reservations using actual `resource_id`, `start` and `end`. Full 28-train plan was not confirmed. Restriction scenario showed unsupported status.
- CSV downloaded and verified on disk: six columns (`timestamp,train_id,block_id,speed_kmh,delay_min,quality_index`), SIM IDs and actual captured snapshot values.
- Only the preview's verified uvicorn process on port 8012 was stopped. Last snapshot froze at 11:00:50, all 28 rows stayed visible and reconnection error appeared. Restart resumed at 11:01:12 without rollback and hid the error.
- 390 × 844 viewport: document clientWidth and scrollWidth both 380 px (browser scrollbar occupies the remainder). The diagram scrolls locally at 820 px. Incident select fills its control row (356 px). No page-wide horizontal overflow.
- Final preview returned to standard viewport, light theme, RU and live SSE. Screenshots: `demo-preview/realtime.jpg` and `demo-preview/realtime-mobile.jpg`.

## Limits

Synthetic Kazakhstan data only, advisory demo. 3D lanes and switch drawings are illustrative; exact track allocation is unavailable. Pair reservations are not executed in playback. Physical acceleration/braking, energy, signal/switch telemetry, PDF export and full 28-train conflict-free execution remain incomplete. Quality excludes block overlaps and energy; block overlaps are reported separately. No <500 ms / frame-rate certification, native-speaker Kazakh review, or forced GPU-loss test.
