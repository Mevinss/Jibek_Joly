# Sources and licenses

Imported on 2026-10-01 from the user-supplied team reference:
https://jol-digital-station.albinaaa2006.chatgpt.site/

`app.js`, `engine.js`, `scene.js` and `reference.css` derive from that site's public app.js, engine.js, scene.js and style.css. Adaptations include Jibek Joly branding, locale resources, SIM identifiers, local dependencies, API workspace and theme. This attribution is not a claim that the team's code has a particular open-source license.

`workspace.js`, `approach.mjs`, `combined.css`, locale wiring and integration documentation were added in this branch.

Vendored dependencies:

- Three.js revision 180 (0.180.0): three.module.js, three.core.js and OrbitControls.js, MIT. Source: https://github.com/mrdoob/three.js/tree/r180 . License: vendor/THREE-LICENSE.
- Leaflet 1.9.4: JavaScript, CSS and marker/layer images, BSD-2-Clause. Source: https://github.com/Leaflet/Leaflet/tree/v1.9.4 . License: vendor/LEAFLET-LICENSE.

Reference maps can request OpenStreetMap tiles and retain attribution to https://www.openstreetmap.org/copyright . Tiles require internet; country geometry is bundled. The API workspace uses local geometry without remote tiles. Existing country geometry and font attribution remain in the repository's original source records. Three.js, Leaflet, fonts, calculations and 3D do not require a runtime CDN.
