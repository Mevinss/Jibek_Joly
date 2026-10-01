# Combined demo implementation plan

> **For agentic workers:** Execute the approved user request inline, using superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Produce a runnable combined demo on codex/combined-demo.

**Architecture:** Adapt the published vanilla JOL app and preserve its deterministic scenario engine and Three.js station. Add separate modules for a real Jibek Joly snapshot workspace and scenario speed illustration; use the existing FastAPI static serving and APIs.

**Tech Stack:** HTML, CSS, JavaScript modules, Three.js, Leaflet, existing Python FastAPI.

**Spec:** ../specs/2026-10-01-combined-demo-design.md

## Global constraints

- All new visible copy comes from RU/KK locale resources; Kazakh is unreviewed.
- Kazakhstan routes, visible SIM identifiers, no operational/safety claims.
- No hard-coded optimizer improvement or ML prediction.
- Preserve main backend contracts and source-state boundaries.

## Review focus

- Navigation while an API request is pending must discard stale results.
- Stream errors must freeze state and show recovery.
- Invalid/expired speed slots must be unavailable.
- WebGL loss must leave a usable table and scheme.
- Narrow screens must retain readable, locally scrollable diagrams.

## Tasks

- [x] Import published reference modules/vendor assets, add attribution/licenses, preserve old entry.
- [x] Adapt brand/theme/locales and add real snapshot workspace and evidence view.
- [x] Add computed scenario speed illustration with boundary/error tests.
- [x] Verify navigation, 3D, scenario/game, API failures, responsive layout and language/theme.
- [x] Review diff, commit on the separate branch and deliver local preview.

Validation evidence and remaining backend baseline failure: `docs/COMBINED_DEMO_VALIDATION.md`. Work stays on the requested local branch; no merge/push.
