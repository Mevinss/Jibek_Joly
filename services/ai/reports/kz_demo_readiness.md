# Kazakhstan demo and model audit — 2026-10-01

## What the uploaded archive actually contains

`D:\kz_kokshetau_astana_almaty_data.zip`, SHA-256 `adc942a361248d9bcc8b598de3c0e18c2a5621cf6ecceada88fa6959aae0dffe` (see machine-readable audit for canonical hash).

9 Kazakhstan stations, 8 major segments, 56 synthetic blocks, 28 SIM services, 156 scheduled stops, 112 mock signals and 7 mock switches. All 14 files under `data/` match the verified `main` KZ fixture after newline normalization. The archive adds no actual journey observations. README and incident JSON are data context, not executable instructions.

There are no `actual_arrival`, `actual_departure`, measured delay changes or conflict labels. Existing PKP delay weights therefore were not re-labelled as a Kazakhstan-trained delay model.

## Separate training completed

`kz-synthetic-schedule-v1` is a LightGBM regressor trained from the supplied archive. Target: scheduled arrival minus previous scheduled departure in minutes. Inputs: synthetic segment distance, speed limit, service category, destination track count, direction. IDs and scheduled target values are not input features.

128 interstation examples: 67 training, 29 validation, 32 test. Entire SIM train IDs are disjoint across splits (15 / 6 / 7 services). Candidate selection uses validation MAE; final test is held out. Route segments recur across the train-ID split; the test is deliberately not described as unseen-route validation.

| Test | MAE |
| --- | ---: |
| Held-out SIM services, familiar segments | 0.566 min |
| RMSE on the same test | 0.927 min |
| Distance / speed-limit baseline | 61.005 min |
| Training segment-median baseline | 22.094 min |
| Separate diagnostic: completely unseen Шу — Алматы segment | 38.245 min |

The last result is the central limitation: the model largely learns this timetable's relationships. It is an educational model, not accepted for operational use. It cannot establish accuracy for actual ҚТЖ delays. The scheduled CSV remains the source of truth for playback; the model does not overwrite it.

Artifacts: `models/kz_schedule_demo/model.txt`, `metrics.json`; reproducible training: `python -m services.ai.training.train_kz_schedule --data-dir data/kz-upload/data/KZ`. No external API or OpenAI credit is needed to train this tabular model.

## Existing delay model quality

The separately retained `pkp-main-298694c` model predicts next-segment delay change and a calibrated proxy (delay growth ≥3 min or specified disruption categories). On held-out PKP runs: MAE 0.586 min (~35 seconds), RMSE 2.506 min, ROC-AUC 0.880, PR-AUC 0.266, precision 19.8%, recall 75.6%. Temporal month holdout MAE 0.823 min. About 80% of warnings at the selected threshold are false positives. ROC-AUC is not “88% accuracy”.

These metrics are for PKP, not Kazakhstan. Kazakhstan inference currently uses the generic PKP profile, not an invented mapping between unrelated real rail segments. Freight uses visibly marked rules. To train a real KZ delay model we need measured arrival/departure timestamps, schedule versions, train/route IDs, disruptions, and enough separate days to split chronologically without leakage.

## Requested map plan

| Requirement | Status in this AI demo |
| --- | --- |
| Kazakhstan-only geography and routes | Implemented: Көкшетау-1 — Курорт-Бурабай — Ақкөл — Астана-1 — Қарағанды — Ақадыр — Сарышаған — Шу — Алматы-2 |
| MapLibre, paper palette | Implemented, library 5.6.2 self-hosted with license |
| Offline fallback | Local map geometry and SVG mode; no external tiles required. Local Python service must stay running. LLM needs network. |
| Real railway geometry | Partial: factual station coordinates; straight connections, synthetic block lengths. Not surveyed rails. |
| GET /infra/geometry | Implemented, GeoJSON plus station and source metadata; retained fixture block IDs |
| Position (block_id, km) | km is distance from the block's canonical start, independent of train direction; display carries direction |
| Live stream | SSE 1Hz, tick measured ~1.03s; x10 is simulation speed, separate chaos scenario imposes delays on ten trains and a closure |
| Smooth movement | Browser extrapolation, correction over250ms, stale extrapolation bounded to1.3s; one setData for all train points per frame |
| Train type, delay color, selection, tooltip ETA | Implemented. All trains available in selector; only selected map label expanded to reduce overlap |
| Scheduled ghost / trail / future line | Implemented for selected train. Future uses current speed, not solver or ML arrival trajectory |
| Station occupancy ring and problem indicator | Implemented from simulation, not live infrastructure |
| Station scheme | Conditional schematic with synthetic tracks; not actual switches or certified station plans |
| Linked train diagram | Implemented, click/keyboard selection shares train with map and inspector; station rows evenly spaced |
| History and CSV | Browser-memory rolling15min, recorded since page load; replay and CSV export. No server persistence |
| Follow train / incident focus / layers | Implemented; SVG fallback has simpler camera behavior |
| Two physical tracks | Not claimed: supplied KZ fixture uses direction locks. Marker offset only separates directions visually |
| ML block profiles from actual KZ delays | Not available: archive contains no observed delay history |
| Integration with main platform/solver | Pending; this page uses its own explicitly labelled timetable playback |

## DOCX acceptance audit

The attachment requests a complete multi-service advisory dispatch prototype. This branch contributes ML/LLM and presentation playback; it is not a verified end-to-end delivery of every team member's subsystem.

Done here: local web app, 1Hz SSE, basic reconnection/backoff, schema validation, ML forecasts, grounded read-only chat, OpenAPI, health/compute metrics, visible demo labels, map/diagram/scheme, incident demonstrations, history replay and CSV.

Pending integration and acceptance tests: conflict-free optimizer under capacity/priority constraints; real alternatives after incidents; ATO speed/energy recommendations; transparent quality-index formula and factor breakdown; normalized live signal/switch feed; deduplication/noise filtering against platform events; durable24–72h history; authentication/roles; queue architecture; measured event-to-visible-plan <500ms and solver latency; actual x10 event-burst load test; PDF report; final10–12slide presentation/demo recording. Existing main-platform implementations have not been declared absent; they are simply not wired to this page or end-to-end accepted here.

Prioritize solver/platform integration over additional UI decoration. Next priority is a labelled real Kazakhstan event history for valid ML evaluation. Do not manufacture an improvement over FIFO, an energy saving or a quality score.

## OpenAI credit

The supplied screenshot shows a $50 promotion already applied, not a remaining-balance statement. Re-entering it cannot add another $50. Confirm remaining credit and expiry in [Credit grants](https://platform.openai.com/settings/organization/billing/credit-grants).

Use credit for the existing read-only assistant: select tools, explain the chosen snapshot, answer model questions and produce draft summaries. The KZ timetable tool is separate from the PKP risk tool; forecasts are rendered from tool evidence with explicit synthetic/proxy warnings. Later, document retrieval or voice input can improve the demo, but are not needed to train LightGBM.

At the checked [GPT-4.1 mini rates](https://developers.openai.com/api/docs/models/gpt-4.1-mini), $0.40/M input tokens and $1.60/M output tokens, a total of5000input+1000output tokens costs about$0.0036. Multiple tool rounds enlarge those totals. A hypothetical untouched$50 would fund about13889 such token bundles, not a guaranteed number of conversations. Rate limiting and max output tokens are present; no hard dollar-budget enforcement is implemented.

## Sources and distribution

Station coordinate sources are recorded individually in `demo/corridor.json` under `coordinate_source` (Railwayz.info; linked attribution, noncommercial presentation use). Country boundary: Natural Earth, public domain. Optional OSM raster tiles are fetched only for the viewed map; attribution is visible; no bulk download or offline tile cache is implemented, following the [tile policy](https://operations.osmfoundation.org/policies/tiles/). Uploaded KZ schedule is explicitly synthetic. PKP dataset attribution remains with the original model.
