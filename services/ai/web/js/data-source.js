'use strict';
// Stage 1 reads generated static mock files. Backend mode is a typed placeholder only.
window.Stage1DataSource = Object.freeze({
  SOURCE: 'mock',
  async load() {
    const paths = ['/assets/mock/dataset.json', '/assets/map/station_coords.json',
      '/assets/map/route_geometry.json', '/kazakhstan.geojson'];
    const responses = await Promise.all(paths.map(path => fetch(path)));
    for (const response of responses) if (!response.ok) throw Error(`HTTP ${response.status}`);
    const [dataset, stations, routes, country] = await Promise.all(responses.map(response => response.json()));
    if (dataset.source !== 'MOCK') throw Error('Unexpected data source');
    return {dataset, stations, routes, country};
  },
  /** @returns {Promise<{dataset: object, stations: object[], routes: object[], country: object}>} */
  async loadBackend() {
    // TODO: bind Canonical State v2 after its frontend integration contract is approved.
    throw Error('Backend data source is not connected in stage 1');
  },
});
