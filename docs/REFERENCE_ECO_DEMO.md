# JibekJoly reference demo

Branch: `codex/jibekjoly-eco-demo`. The entry point is `frontend/index.html`.
The team's current website source is preserved in `services/ai/web/jibekjoly`;
provenance is recorded in its `SOURCE.md`. The former combined workspace remains
available at `/combined/` and the old dispatcher at `/dispatch-original.html`.

## Run and present

Use Python 3.11, install `services/ai/requirements.txt`, and run
`python -m services.ai.main` from the repository root. Open `http://127.0.0.1:8002/`.
No Node build is needed. Node is used only for development checks and fixture export.

1. On **3D-коридор**, select **SIM-FRT-208**. It starts halfway between Астана and
   Қарағанды: 7 model km remain, the next main-track signal opens at 08:10,
   the limit is 80 km/h, and the calculated recommendation is approximately 42 km/h.
2. The train card has the speed profile and a predicted `full stop avoided` badge.
   Run the simulation; the confirmed badge is earned only after actually entering
   the next block without the model waiting for a full stop. Turning Eco off uses
   the ordinary speed and causes a stop in this example.
3. Click a station in 3D or choose one on the arrival board. The board simulates a
   copy of the exact current snapshot, including occupancy and known restrictions.
   Text and colours distinguish ≤5, >5–15 and >15 minutes of delay. A held train's
   future ETA can be unknown. Future untriggered incidents are excluded.
4. Open **Сценарии**, choose a case and press **Итог**. Each side receives the same
   train package and the same incident block/time. The managed side uses repair,
   reserve, priority and Eco; it is not a controlled experiment isolating Eco alone.
5. **Поездограмма и план** compares six policies in a Web Worker. An outdated or
   archived plan cannot be applied to the current trip. History, profile charts,
   CSV and PDF use the selected trip; archived Eco controls are disabled.

## Data and limits

`kz-eco-synthetic-v1`, seed 20261002, contains six SIM trains with speeds,
mass, scheduled release times, an initial position and a known signal window.
Nine Kazakhstan station names follow the team reference. Distances, topology and
schedule are compressed demonstration inputs, not operational ҚТЖ data.

Eco advice is an idealized constant-speed profile with instantaneous speed changes.
It has no validated braking curves or safety envelope. Unknown openings, a closed
current block, unreachable windows and required speeds below 5 km/h do not produce
an actionable target. Advisory availability and confirmed simulation stop avoidance
are distinct. Terminal arrival is excluded from intermediate stop counts.

The mass/speed/idle/stop proxy uses arbitrary units; it is not diesel litres, kWh or
validated fuel savings. Whole-trip proxy accounting also counts speed reductions.
The five-factor movement index is a transparent heuristic, not ML accuracy. The
existing PKP forecaster and Kazakhstan synthetic schedule model remain separate.
The new UI does not silently show unrelated fixture forecasts or ML results.

Live motion here is a browser simulation. `/eco/advice` computes on submitted inputs;
the card's server-check button pauses playback and confirms the captured snapshot
or shows a request error. This interface does not claim to consume ҚТЖ telemetry.
Unreviewed Kazakh translation is marked in the UI.

## Reproduce and verify

```powershell
python -m services.ai.scripts.export_eco_package
python -m services.ai.scripts.export_contracts
node scripts/export-eco-demo.mjs
node --test tests/eco-demo.test.mjs
python -m pytest services/ai/tests -q
```

`docs/eco-demo-evaluation.json` records actual scenario outputs, with all six trains
finished. It is evidence, not the source of displayed improvements. The UI runs the
simulator again. In the speed-restriction scenario the managed energy proxy rises;
this is shown as a deterioration even though delay and index improve.

Verified: 46 backend tests, six frontend simulation tests, browser train/station
selection, API confirmation, policy calculation, scenario end results, archival
read-only controls, locale/theme controls and 390 px layout. PDF generation was
checked with the bundled report function; browser showed “Отчёт готов”.
