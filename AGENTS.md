# TurkiSib project instructions

## Scope and truth
- This repository's AI service is an advisory hackathon demo, not a train control system.
- Keep the dispatch scenario labelled as demonstration input. Predict with the actual model; never hard-code improved predictions or optimizer benefits.
- `p_conflict_15m` is a legacy contract name for a next-segment proxy. It is not a validated 15-minute conflict probability. Explain that distinction in UI and chat.
- Unsupported train types use `rule_fallback`; label that as a heuristic, not ML.
- Geographic demo and train routes must be Kazakhstan-only. Keep SIM identifiers visible; the uploaded Kazakhstan package is synthetic, not operational ҚТЖ data.
- `kz-synthetic-schedule-v1` learns scheduled segment duration, not delay. Its synthetic test MAE must never be presented as accuracy on real Kazakhstan journeys. Keep it separate from the PKP delay forecaster.
- SHAP contributions describe classifier log-odds before calibration, not causality or percentage-point contributions.
- Chat with a supplied snapshot must only use that snapshot for state and forecasts. Do not substitute unrelated fixture plans or solver results.

## Development
- Python 3.11. Install `services/ai/requirements.txt`; start `python -m services.ai.main` from the repo root (default localhost:8002).
- The interactive UI is `services/ai/web`, served by FastAPI. No Node build is required.
- Run `python -m pytest services/ai/tests -q` after meaningful backend changes. Run `python -m services.ai.scripts.export_contracts` after schema changes.
- Check UI controls, request failures, keyboard focus and narrow-screen layout when editing the demo. Keep user-visible copy in RU/KK locale files, use explicit units, and mark unreviewed Kazakh translations. The visible brand is ТүркіСіб, with an own logo and no subtitle.
- Read PRODUCT.md and DESIGN.md before extending the interface. They describe the product and current UI; no particular design plugin is required.

## Data and credentials
- Never print, commit or send `.env` credentials to the frontend. OpenAI calls are server-side only.
- Raw datasets, local environments and logs stay gitignored. Commit small model artifacts, source attribution and reproducible evaluation evidence.
- Do not overwrite another team member's changes. Use `codex/` branches unless the user specifies another branch (`feat/design-turkisib` for the redesign); validate before pushing. Do not merge without authorization.
