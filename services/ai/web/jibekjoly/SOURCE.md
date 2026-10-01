# Team site source

Adapted from the user-supplied team repository:
https://github.com/albina0dali/Jibek_Joly/tree/642d6a48a877e29b9b7a9526a242240173477b63/web

The continuous 3D corridor, nine stations, original interface, local planner,
journey charts and export are preserved. Hosting/account-only controls have been
removed because this demo runs on the repository's FastAPI service.

Added: the `kz-eco-synthetic-v1` package, freight Eco-driving advisory,
station arrivals from the current snapshot, actual stop/proxy accounting,
RU/KK strings and `/eco/advice` API.

Three.js, OrbitControls and report-font license files are in `vendor`.
The checked-in report bundle uses pdf-lib 1.17.1, @pdf-lib/fontkit 1.1.1
and esbuild 0.28.2. These are development dependencies; running the app
does not require Node or npm.
