# Kazakhstan synthetic demo data

This directory is the single source for the Kokshetau–Astana–Almaty simulator fixture. `KZ/` holds the synthetic route, block, train and timetable tables; `mock/` holds simulated signals, switches and train parameters; `scenarios/` holds initial state and four incident definitions. `validation.json` records expected package counts.

All train IDs beginning with `SIM-` and all operational states are simulated. Station names refer to real places, but the movements and disruptions are not actual Kazakhstan services. PKP and DISPLIB remain in `data/external/` and are never merged here.
