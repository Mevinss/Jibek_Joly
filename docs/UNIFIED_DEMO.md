# AI Railway Decision Center demo

## Run on Windows

From the repository root in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn services.ai.main:app --host 127.0.0.1 --port 8002
```

Open `http://127.0.0.1:8002/`. The main scenario is **28 поездов · единый
симулятор**. The old frontend is at `/legacy`.

## Show the full flow

1. Confirm the 28 train markers, 28 rows in the route-progress train graph,
   and the shared `run_id · snapshot` label.
   The map is an approximate diagram. Choose a train or station to inspect
   details, ETA and the line speed limits.
2. Optionally press **Продолжить** and choose ×1, ×10 or ×60. Press
   **Пауза** before comparing alternatives so all results use one snapshot.
3. In **Инцидент**, choose `BLOCK_CLOSURE`, select a block on the route and
   choose five minutes. Press **Внести инцидент**. The incident and affected
   trains appear in the same dashboard.
4. Inspect A/B/C. A means no action; B and C are validated holds on affected
   trains. Each row shows a 20-minute independent simulator projection. The
   recommendation uses weighted delay (intercity 3, regional 2, freight 1).
   It may legitimately recommend A.
5. Select B or C, choose a 10-, 20- or 30-minute forecast, then press
   **Предпросмотр**. Compare projected network delay
   and per-train impacts. Press **Карта прогноза** to see the fork, then
   **Карта сейчас** to return. Confirm the live snapshot number did not change.
6. Press **Применить**. The snapshot number advances and the action appears in
   the event history. ETA, train graph and the snapshot health heuristic refresh.
   In the history row, press **Восстановить снимок** and optionally **Карта
   истории** to inspect the stored read-only state.
7. Press **Сначала** to start a new clean run. Refresh the browser to show
   that the server persists the current run in SQLite.

## What to say

This is a synthetic Kazakhstan railway decision-center demonstration. The
simulator, planner checks and dashboard share one canonical snapshot and run
identity. FIFO and CP-SAT are calculated, but their 28-train station-track
occupancy remains unverified, so the main demo applies only separately
validated human holds. Preview runs on a copy and does not change live state.
The health score is a transparent snapshot heuristic. The speed panel shows
line and train speed limits, not a physically optimal speed. Energy values are
dimensionless proxies and are not kWh, money or CO₂. The system does not
control real trains or replace certified signalling.
