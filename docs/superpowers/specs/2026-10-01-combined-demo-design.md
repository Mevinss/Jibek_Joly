# Combined Jibek Joly demo

The user requests an executable preview of the proposed combined product on a separate branch. Preserve the team's published JOL map, city/station navigation, actual Three.js station, arrival board, four calculated scenarios, dispatcher game and causes analysis. Integrate Jibek Joly's actual 28-train snapshot, timetable diagram, model boundaries and planner pair analysis. This is a demonstration preview, not a completed integration of all backend simulation engines.

Keep Jibek Joly's own logo, Russian default, local Inter/JetBrains Mono, cream/blue light theme and dark theme. Keep Kazakh with a visible translation-review note. SIM IDs and synthetic-data notices stay visible. Scenario metrics are calculated by the imported deterministic engine; ML and CP-SAT results must come from existing APIs. The scenario game's state is distinct from the 28-train backend snapshot and must be described explicitly.

The primary entry is frontend/index.html. Shared assets live in services/ai/web/combined. Preserve the original dispatcher as /dispatch-original.html. No Node build. Self-host the reference's Leaflet and Three.js dependencies and licenses. Record attribution to the user-supplied source and its download date.

New workspace: fetch /demo/snapshot and /infra/geometry; subscribe to /demo/stream at 1 Hz. Render actual observed positions, train register and timetable; request /dispatch/analysis with captured elapsed/incident/seed. Show pair scope and full planner status, explicitly no application to playback. Reconnection freezes the last snapshot. Abort requests and close stream when leaving a page.

New scenario speed preview: derive required average speed from a scenario reservation and an explicitly adjustable synthetic approach distance, obey a declared speed cap; show unavailable if time/distance/cap is invalid or slot is unreachable. No fuel savings. This is a kinematic illustration, not a full ATO profile.

Acceptance: preserved 3D and game work; new workspace uses actual APIs; controls and API failures are visible; no cross-source metric mixing; RU/KK and light/dark work; keyboard navigation, narrow layout and no-WebGL fallback work. No publish/merge requested.
