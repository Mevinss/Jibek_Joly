# JibekJoly reference + Eco-driving implementation plan

> Use executing-plans to implement the existing reference flow in this session.

Goal: Extend the team's actual Jibek_Joly site with synthetic data, target-signal Eco-driving, station arrival boards and calculated scenario comparisons, retaining the complete 3D corridor and original navigation.

Architecture: Import the public reference web source into `services/ai/web/jibekjoly`, retain its client simulation and rendering, and serve it through the existing FastAPI entry point. Add one validated Python Eco-driving API and a matching pure JS advisory helper used by the simulation. A checked-in synthetic package supplies train caps/masses/initial positions and known release windows; its frontend export is reproducible.

Constraints: Brand `JibekJoly`; nine reference Kazakhstan stations; SIM identifiers. Advisory demo, no train control, no claims in litres or kWh. Source attribution to albina0dali/Jibek_Joly at imported commit. Preserve both other frontends and backend endpoints. RU/KK new copy in locale files; KK unreviewed.

- [x] Capture reference provenance, mount source, preserve source styling and local vendor assets.
- [x] Test and implement target-time advisory: unknown/past target, speed cap, stopped/held train, too-slow approach, exact 7 km / 10 min average 42 km/h; return energy_proxy_units, full_stop_avoided, recommended_speed_profile, target_arrival_time.
- [x] Apply recommendation only on an open current block approaching a known red next signal; never pass a closed signal. Count predicted vs confirmed avoided stops separately; record actual energy and speed. Compare identical synthetic input before/after with actual simulation metrics.
- [x] Add train card and station arrival board from selected world, predicted arrival by forward simulation, delay text + semantic colours. Add dedicated profile view and reproducible data inspector; maintain scenario/game/plan/history workflows.
- [x] Run backend and meaningful frontend simulation tests, review source, verify desktop/mobile interactions and errors, save screenshots and commit on the separate branch.

Review focus: frame replay must preserve new advice fields; estimates must not change live world; unknown next-block release must not promise an avoided stop; case comparison must use identical train definitions; units and the synthetic disclaimer must remain visible.
