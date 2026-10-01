# PKP Intercity train delays dataset

## Dataset summary

This repository contains an open-access dataset of passenger train operations run by the primary Polish long-haul passenger carrier (PKP Intercity), recorded infrastructure disruptions, and co-located meteorological parameters spanning from **March 1, 2026 to May 19, 2026**.

The dataset provides raw operational database tables, mapped physical infrastructure topology, processed flat tabular features, structural graph representations, route sequence tensors, and standardized benchmark splits for train delay prediction models.

---

## Directory structure

```text
pkp_intercity_delays_dataset/
├── README.md
├── LICENSE
├── raw/
│   ├── run_stops.csv                  <- Raw train stop arrival and departure records
│   ├── run_stop_difficulties.csv      <- Raw textual disruption logs linked to train stops
│   ├── difficulties.csv               <- Disruption category lookup table
│   ├── train_services.csv             <- Train service registry and commercial metadata
│   ├── train_categories.csv           <- Commercial train category lookup (EIP, EIC, IC, TLK)
│   ├── occupancies.csv                <- Passenger occupancy level definitions
│   ├── stations.csv                   <- Railway station registry and physical features
│   ├── line_stations.csv              <- Station kilometrage alignment along railway lines
│   ├── railway_lines.csv              <- Physical railway line registry
│   ├── platforms.csv                  <- Station platform and track capacity attributes
│   ├── line_speeds.csv                <- Permissible line speeds by track and direction
│   ├── service_line_segments.csv      <- Physical line segment mapping for train routes
│   ├── track_closures.csv             <- Planned track closures and maintenance schedules (SHZT)
│   ├── speed_warnings.csv             <- Temporary speed restrictions (WOS)
│   ├── weather.csv                    <- Hourly meteorological parameters from Open-Meteo
│   ├── database_schema.png            <- Relational database entity-relationship (ERD) diagram
│   └── raw_documents/                 <- Original PKP PLK network statements and line maps
├── processed_tabular/
│   ├── train_delays_tabular.parquet   <- Preprocessed 57-feature tabular dataset for machine learning
│   └── train_delays_tabular_sample.csv<- 5,000-row preview sample
├── graph_and_sequences/
│   ├── graph/
│   │   ├── nodes_features.parquet     <- Station node topological and physical features
│   │   └── edges_features.parquet     <- Track segment edge features
│   ├── sequences/
│   │   └── route_sequences.parquet    <- Preprocessed route sequence tensors for sequential models
│   └── splits.json            <- Benchmark train (23,531 runs), validation (5,042), and test (5,044) split assignment dictionary
└── examples/
    └── dataset_loader_demo.py         <- Python demonstration script for dataset ingestion
```

---

## Data sources and provenance

1. **Train operational and disruption logs**: Daily train schedules, actual arrival and departure timestamps, delay values, passenger occupancy levels, and disruption report details (cause descriptions and spatial locations logged by dispatchers) collected via automated pipelines from public passenger information interfaces (Portal Pasażera and intercity.pl).
2. **Infrastructure status and line mapping**: Railway line specifications, temporary speed restrictions (WOS), track closure schedules (SHZT), and physical track attributes derived from PKP Polskie Linie Kolejowe (PKP PLK) network statements (_Regulamin Sieci PKP PLK_). Commercial route sequences are mapped onto physical railway line segments (`service_line_segments.csv`).
3. **Meteorological data**: Hourly weather measurements retrieved from the Open-Meteo API, spatially assigned to station clusters derived via spatial DBSCAN clustering across Poland.

---

## Key definitions and methodology

- **Train run (`run_id`)**: A single scheduled journey of a train from its origin station to its destination station on a specific date.
- **Segment / edge (`segment_id`)**: A directed physical railway section connecting two consecutive scheduled station stops along a train route (`prev_station_id` to `station_id`), formatted as `fromStationId_toStationId`.
- **Atomized edge representation**: In the graph representation, edges are defined as atomized physical track segments between adjacent stations across the network rather than long commercial stop-to-stop jumps. This eliminates duplicate overlapping edges and ensures a consistent graph topology across different train service categories.
- **Delay delta (`delta_delay`)**: Primary target variable representing the change in delay (in minutes) accumulated over a single segment or station stop, calculated as current arrival delay minus previous departure delay (`delay_arrival_min - prev_delay_departure_min`). Initial origin stops (`stop_order = 1`) are excluded from target modeling because delay delta is defined between consecutive stops.
- **Departure delay imputation**: For missing initial departure delays at origin stations (`stop_order = 1`), an auxiliary XGBoost regressor is used to estimate departure delay from initial station attributes and subsequent arrival metrics (`is_prev_departure_delay_imputed`). For rare missing departure delay values at intermediate station stops, departure delays are estimated using arrival delays at the same station.
- **Weather threshold optimization**: Decision thresholds for binary weather indicators (`is_freezing_threshold` at <= -2.75°C, `is_heavy_precipitation` at > 0.25 mm/h, `is_frost_and_precip`, and `is_rain_with_snowcover`) were derived during exploratory data analysis using single-split decision trees to select split points maximizing variance reduction of delay deltas.

---

## Structural dataset representations (`graph_and_sequences/`)

Unlike `processed_tabular/train_delays_tabular.parquet` (which provides a single flat table ready for tabular models like XGBoost), files in `graph_and_sequences/` provide decoupled structural inputs for deep sequence models (GRU, LSTM), graph neural networks (GNN, TransformerConv), or hybrid architectures.

These structural datasets serve distinct roles and require preprocessing before inputting into neural networks:

1. **`graph/nodes_features.parquet`** (487 station nodes, 22 attributes): Static station topology attributes (coordinates, platform/track counts, line junction counts) and 8-dimensional historical disruption category profiles (`flavor_node_0` through `flavor_node_7`).
2. **`graph/edges_features.parquet`** (1,172 atomized track edges, 17 attributes): Static segment characteristics (theoretical transit weight, historical delay delta percentiles P50/P90/MAD) and 8-dimensional disruption category profiles (`flavor_edge_0` through `flavor_edge_7`).
3. **`sequences/route_sequences.parquet`** (588,239 stop records, 58 attributes): Chronological route stop sequences per train run. Unlike the tabular dataset, **it retains origin stops (`stop_order = 1`)** to allow recurrent neural networks (GRU/LSTM) to initialize hidden states. It contains explicit sequence lag features (`lag1_delta_delay`, `lag2_delta_delay`, `lag7_delta_delay`, `lag1_stop_delay`, `lag2_stop_delay`, `lag7_stop_delay`) and indicator flags for missing lags.

To construct input batches for neural models, train runs in `route_sequences.parquet` must be grouped by `run_id`, sliced into sliding sequence windows, and mapped to node indices in `nodes_features.parquet` using `splits.json`. An ingestion implementation is provided in `examples/dataset_loader_demo.py`.

---

## Processing and standardization of infrastructure disruptions

Disruption descriptions logged by dispatchers in operational systems (`difficulties`) initially exhibited high textual cardinality (175 unique phrases). Data cleaning was implemented in two stages:

1. **Stage 1: Text cleaning and spatial location extraction**: Regular expressions strip technical notes and track layout markers. When spatial location text is present (such as track segment identifiers or station names), it is extracted as a standalone spatial attribute (`location`). Missing values in `location` stem from entries where no specific location was entered in the operational log.
2. **Stage 2: Categorical standardization**: Cleaned descriptions are mapped onto 43 standardized categories (such as rolling stock failure, catenary breakdown, severe weather conditions, or interlocking device malfunction).

- `difficulty_id` (int8, 0–43): Standardized disruption category logged for this specific train run at the station (0 = No disruption, 1–43 = Specific category; see Disruption lookup table). Retained for post-hoc analysis and historical aggregation; note potential target leakage if used as an input feature for real-time target prediction.
- `edge_active_difficulty_id` (int8, 0–43): Most severe active disruption category logged on the track segment by other trains within a 2-hour window prior to departure. Represents real-time traffic hazard intensity along the segment without target leakage.

---

## Feature schema: `processed_tabular/train_delays_tabular.parquet`

The tabular dataset contains **558,334 stop records** and **57 features** (sorted chronologically by `run_id` and `stop_order`).

### 1. Target variable and operational disruption features

- `delta_delay` (float32, minutes): Primary target variable — change in delay between current arrival delay and previous station departure delay.
- `difficulty_id` (int8): Standardized disruption category ID logged for this train run at the station (0 = No disruption, 1–43 = Specific category; see Disruption lookup table). Note: potential target leakage if used for real-time target prediction.
- `prev_delay_departure_min` (float32, minutes): Departure delay recorded at the preceding station stop.
- `is_prev_departure_delay_imputed` (int8): Binary flag (1 if origin departure delay was estimated using the auxiliary XGBoost regressor, 0 otherwise).

### 2. Primary identifiers and route order

- `run_id` (int32): Unique identifier of the train run.
- `station_id` (int64): Unique identifier of the railway station.
- `stop_order` (int16): Sequential 1-based index of the station stop along the train run route (starts at `stop_order = 2` for delta delay targets).
- `segment_id` (categorical): Directed track segment identifier (`fromStationId_toStationId`).
- `service_id` (int64): Commercial train service number (e.g., train run identifier code).
- `category_code` (categorical): Train commercial category code (`EIP`, `EIC`, `IC`, `TLK`).
- `distance_from_start_km` (float32): Cumulative distance in kilometers from the route origin station.
- `is_international` (int8): Binary flag (1 if train service is international, 0 if domestic).

### 3. Timetable and technical reserve features

- `min_technical_time_min` (float32, minutes): Minimal empirical travel time for the segment, calculated as the 1st percentile of unhindered actual travel times across historical runs.
- `time_reserve_min` (float32, minutes): Timetable buffer time allocated on the segment (`scheduled_travel_time - min_technical_time_min`).

### 4. Passenger occupancy features

- `occupancy_id` (int64 / categorical): Foreign key identifier mapping to discrete passenger occupancy level categories recorded from PKP Intercity (4 = < 50%, 5 = 50%–80%, 6 = > 80%).
- `occupancy_level` (int8): Integer ordinal representation of passenger occupancy level (1 = < 50%, 2 = 50%–80%, 3 = > 80%).

### 5. Cyclical temporal and calendar features

- `day_of_week` (int8): Index of the day of week (0 = Monday, 6 = Sunday).
- `day_category` (categorical): Polish calendar day category classification (`Inny`, `Dzień przed świętem`, `Dzień po święcie`).
- `arrival_hour_sin` (float32): Sine transformation of scheduled arrival hour (24-hour cycle).
- `arrival_hour_cos` (float32): Cosine transformation of scheduled arrival hour (24-hour cycle).
- `departure_hour_sin` (float32): Sine transformation of scheduled departure hour (24-hour cycle).
- `departure_hour_cos` (float32): Cosine transformation of scheduled departure hour (24-hour cycle).
- `month_sin` (float32): Sine transformation of calendar month (12-month cycle).
- `month_cos` (float32): Cosine transformation of calendar month (12-month cycle).

### 6. Dynamic infrastructure disruptions and maintenance metrics

- `edge_active_difficulty_id` (int8): Standardized disruption category ID logged on the segment by other trains within a 2-hour sliding window prior to departure (0 = No disruption, 1–43 = Specific category).
- `edge_active_difficulty_p90` (float32): 90th percentile historical disruption severity score for active segment disruptions.
- `is_track_closure` (int8): Binary flag (1 if an active track closure or line maintenance is present on the segment derived from PKP PLK statements, 0 otherwise).
- `track_closure_length` (float32, km): Cumulative physical length of active track closure on the segment.
- `is_speed_warning` (int8): Binary flag (1 if a temporary speed restriction TSR is active on the segment, 0 otherwise).
- `speed_warning_length` (float32, km): Cumulative physical length of active temporary speed restriction on the segment.

### 7. Historical rolling statistics (30-run window)

- `station_scheduled_dwell_time_P50` (float32, minutes): Median scheduled station dwell duration.
- `station_scheduled_dwell_time_MAD` (float32, minutes): Median Absolute Deviation (MAD) of scheduled station dwell duration.
- `station_scheduled_dwell_time_P90` (float32, minutes): 90th percentile of scheduled station dwell duration.
- `station_delta_stop_min_P50` (float32, minutes): Historical median delay change added or absorbed during station dwell stop.
- `station_delta_stop_min_MAD` (float32, minutes): Historical MAD of delay change during station dwell stop.
- `station_delta_stop_min_P90` (float32, minutes): Historical 90th percentile delay change during station dwell stop.
- `edge_delta_edge_min_P50` (float32, minutes): Historical median travel time delay delta accumulated over the segment.
- `edge_delta_edge_min_MAD` (float32, minutes): Historical MAD of segment travel delay delta.
- `edge_delta_edge_min_P90` (float32, minutes): Historical 90th percentile of segment travel delay delta.
- `edge_delta_delay_P50` (float32, minutes): Historical median overall delay change on the directed edge.
- `edge_delta_delay_P90` (float32, minutes): Historical 90th percentile overall delay change on the directed edge.
- `edge_delta_delay_MAD` (float32, minutes): Historical MAD of overall delay change on the directed edge.

### 8. Weather and environmental features

- `temperature_2m` (float32, °C): Air temperature at 2 meters height.
- `snowfall` (float32, cm): Hourly snowfall amount.
- `snow_depth` (float32, m): Ground snow cover depth.
- `is_freezing_threshold` (int8): Binary flag empirically thresholded via decision tree (1 when `temperature_2m` <= -2.75°C, 0 otherwise).
- `is_heavy_precipitation` (int8): Binary flag empirically thresholded via decision tree (1 when hourly precipitation `precipitation` > 0.25 mm/h, 0 otherwise).
- `is_frost_and_precip` (int8): Binary flag (1 when freezing temperature `temperature_2m` < 0.0°C coincides with active precipitation `precipitation` > 0.25 mm/h, 0 otherwise).
- `is_rain_with_snowcover` (int8): Binary hazard flag (1 when liquid rain `rain` > 0.35 mm/h falls onto existing snow cover `snow_depth` > 0.075 m, leading to track icing, 0 otherwise).

### 9. Station topology and physical infrastructure features

- `passenger_volume_rank` (float32): Railway station category rank according to annual passenger exchange volume.
- `num_platforms` (int8): Number of passenger platforms at the station.
- `num_platform_tracks` (int8): Number of platform tracks at the station.
- `intersecting_lines_count` (int8): Number of intersecting railway lines meeting at the station.
- `is_node` (int8): Binary flag (1 if station is a major railway junction node meeting >= 3 railway lines with non-null passenger volume, 0 otherwise).
- `is_passing_loop` (int8): Binary flag (1 if station functions as a passing loop on single-track lines based on PKP PLK station discriminators M, ML, MLP, MPO and > 1 platform track, 0 otherwise).
- `node_historical_hazard_intensity` (float32): Historical hazard frequency score computed for the station node.
- `edge_historical_hazard_intensity` (float32): Historical hazard frequency score computed for the segment edge.

---

## Feature schema: `graph_and_sequences/` datasets

### 1. Station node features (`graph/nodes_features.parquet`)

- `id` (int64): Station unique identifier.
- `name` (string): Station name.
- `latitude`, `longitude` (float64): Geographical coordinates.
- `passenger_volume_rank` (float32): Annual passenger exchange volume rank.
- `is_domestic` (int64): Flag indicating whether the station is domestic (1) or international (0).
- `num_platforms`, `num_platform_tracks` (int64): Physical platform and platform track counts.
- `intersecting_lines_count` (int64): Number of intersecting railway lines meeting at the station.
- `is_node` (int64): Binary flag for major railway junction nodes.
- `is_passing_loop` (int64): Binary flag for passing loops on single-track lines.
- `stop_count` (int64): Total historical train stops at the station.
- `total_node_difficulties` (int64): Total historical disruptions logged at the station.
- `historical_hazard_intensity` (float64): Ratio of logged disruptions to total train stops.
- `flavor_node_0` through `flavor_node_7` (float64): 8-dimensional historical disruption category profile distribution.

### 2. Track edge features (`graph/edges_features.parquet`)

- `edge_id` (string): Directed track segment identifier (`fromStationId_toStationId`).
- `run_count` (int64): Historical train run count on the edge.
- `weight` (float64): Theoretical transit time in minutes calculated as distance divided by permissible line speed.
- `edge_delta_delay_mean`, `edge_delta_delay_P50`, `edge_delta_delay_P90`, `edge_delta_delay_MAD` (float64): Historical travel delay delta statistics on the edge.
- `total_edge_difficulties` (int64): Total historical disruptions logged on the edge.
- `historical_hazard_intensity` (float64): Ratio of logged edge disruptions to historical train run count.
- `flavor_edge_0` through `flavor_edge_7` (float64): 8-dimensional historical disruption category profile distribution.

### 3. Sequential route features (`sequences/route_sequences.parquet`)

Contains 58 sequence features per stop step. Key sequence-specific attributes include:

- `stop_order` (int16): Sequential stop index starting at `stop_order = 1` (origin stop).
- `lag1_delta_delay`, `lag2_delta_delay`, `lag7_delta_delay` (float32): Historical delay deltas recorded for the train service on preceding days.
- `lag1_stop_delay`, `lag2_stop_delay`, `lag7_stop_delay` (float32): Historical stop delays recorded for the train service on preceding days.
- `is_lag1_delta_missing`, `is_lag2_delta_missing`, `is_lag7_delta_missing` (int8): Indicator flags for missing historical lag values.
- `is_lag1_stop_missing`, `is_lag2_stop_missing`, `is_lag7_stop_missing` (int8): Indicator flags for missing historical stop delay values.

---

## Disruption category lookup table (`difficulty_id` and `edge_active_difficulty_id`)

The table below maps standardized disruption integer codes (`0–43`) to their Polish source category descriptions and English translations.

|  Code  | English Category Translation                      | Polish Category Name                                                      |
| :----: | :------------------------------------------------ | :------------------------------------------------------------------------ |
| **0**  | No active disruption                              | Brak aktywnego utrudnienia                                                |
| **1**  | Fatality / Person on track incident               | Wypadek z udziałem człowieka                                              |
| **2**  | Major accident disrupting train traffic           | Wypadek powodujący przerwę w ruchu pociągów                               |
| **3**  | Level crossing collision with road vehicle        | Wypadek z udziałem pojazdów drogowych                                     |
| **4**  | Emergency services intervention                   | Interwencja służb ratowniczych                                            |
| **5**  | Waiting for preceding train clearance             | Oczekiwanie na przejazd innego pociągu                                    |
| **6**  | Rail traffic management incident                  | Zdarzenie związane z prowadzeniem ruchu kolejowego                        |
| **7**  | Additional unscheduled stops                      | Dodatkowe postoje                                                         |
| **8**  | Rolling stock technical inspection                | Sprawdzenie stanu technicznego taboru                                     |
| **9**  | Power supply equipment failure                    | Awaria urządzeń energetycznych                                            |
| **10** | Telecommunication / Signaling systems malfunction | Usterka systemu łączności                                                 |
| **11** | Shunting / Coupling / Decoupling carriages        | Włączanie/wyłączanie wagonów                                              |
| **12** | Delay caused by external infrastructure manager   | Opóźnienie z winy innego zarządcy infrastruktury                          |
| **13** | Rolling stock failure / Locomotive breakdown      | Awaria taboru                                                             |
| **14** | Railway infrastructure defect                     | Awaria elementów infrastruktury kolejowej                                 |
| **15** | Animal collision on track                         | Kolizja ze zwierzętami                                                    |
| **16** | Interlocking / Signaling devices failure          | Awaria urządzeń sterowania ruchem kolejowym                               |
| **17** | Infrastructure manager operational disruption     | Utrudnienia w prowadzeniu ruchu leżące po stronie Zarządcy Infrastruktury |
| **18** | Railway investment and construction works         | Przyczyny związane z realizacją inwestycji                                |
| **19** | Railway line maintenance works                    | Inne przyczyny związane z utrzymaniem linii kolejowych                    |
| **20** | Other operator operational causes                 | Inne przyczyny związane z działalnością przewoźnika kolejowego            |
| **21** | Other infrastructure manager causes               | Inne przyczyny związane z działalnością zarządcy infrastruktury           |
| **22** | Other unspecified cause                           | Inne                                                                      |
| **23** | Catenary / Overhead contact line breakdown        | Awaria sieci trakcyjnej                                                   |
| **24** | Police / Security services intervention           | Interwencja służb porządkowych                                            |
| **25** | Extended carriage preparation / Servicing         | Wydłużone przygotowanie wagonów do drogi                                  |
| **26** | Medical emergency intervention                    | Interwencja służb medycznych                                              |
| **27** | Extended waiting for station service handling     | Wydłużone oczekiwanie na obsługę                                          |
| **28** | IT / Passenger info system breakdown              | Awaria systemu informatycznego                                            |
| **29** | Extended passenger boarding duration              | Wydłużone lokowanie pasażerów                                             |
| **30** | Severe weather conditions                         | Trudne warunki atmosferyczne                                              |
| **31** | Traction power outage                             | Brak zasilania sieci trakcyjnej                                           |
| **32** | Infrastructure theft / Vandalism                  | Kradzież elementów infrastruktury kolejowej                               |
| **33** | Carrier operational difficulties                  | Utrudnienia w realizacji przejazdu leżące po stronie Przewoźnika          |
| **34** | Delay cascade from another train                  | Opóźnienie innego pociągu                                                 |
| **35** | Temporary speed restriction                       | Ograniczenie prędkości pociągu                                            |
| **36** | Waiting for connecting passenger train            | Oczekiwanie na skomunikowanie                                             |
| **37** | Extended border / Passport control                | Wydłużona kontrola graniczna                                              |
| **38** | Causes independent of carrier and manager         | Przyczyny niezależne od Zarządcy Infrastruktury i Przewoźnika             |
| **39** | Waiting for rolling stock from incoming train     | Oczekiwanie na tabor z innego pociągu                                     |
| **40** | Train run cancellation                            | Pociąg odwołany                                                           |
| **41** | Extended conductor consignment handling           | Wydłużona obsługa przesyłek konduktorskich                                |
| **42** | Fallen tree on catenary                           | Przewrócone drzewo na sieć trakcyjną                                      |
| **43** | Freight train and person collision                | Wypadek z udziałem człowieka i pociągu towarowego                         |

---

## Raw data specifications (`raw/`)

1. **`run_stops.csv`**: Contains raw train stop records extracted from passenger information systems (`id`, `run_id`, `station_id`, `stop_order`, `scheduled_arrival`, `scheduled_departure`, `delay_arrival_min`, `delay_departure_min`, `distance_from_start_km`).
2. **`run_stop_difficulties.csv`**: Textual disruption logs linked to specific stops (`stop_id`, `difficulty_id`, `location`). Missing values (`NaN` / nulls) in the `location` field occur when dispatchers or conductors do not enter a location for a logged disruption entry.
3. **`difficulties.csv`**: Lookup table defining standardized disruption category IDs and Polish/English names.
4. **`train_services.csv`**: Registry of commercial train service numbers, service names, and route endpoints.
5. **`train_categories.csv`**: Commercial train service category definitions (`EIP`, `EIC`, `IC`, `TLK`).
6. **`occupancies.csv`**: Reference table defining passenger occupancy level ranges.
7. **`stations.csv`**: Railway station registry containing geographical coordinates, names, and physical junction features.
8. **`line_stations.csv`**: Station alignment along PKP PLK railway lines including kilometer markers.
9. **`railway_lines.csv`**: Railway line registry containing line numbers and designations.
10. **`platforms.csv`**: Station platform and track capacity attributes derived from PKP PLK statements.
11. **`line_speeds.csv`**: Permissible line speeds mapped by track number and direction.
12. **`service_line_segments.csv`**: Physical railway line segment mapping connecting consecutive train route stops.
13. **`track_closures.csv`**: Parsed track closure schedules (SHZT) including location, dates, line numbers, and maintenance details.
14. **`speed_warnings.csv`**: Active temporary speed restrictions (WOS) filtered for passenger operations.
15. **`weather.csv`**: Georeferenced hourly weather reanalysis measurements retrieved from Open-Meteo (`cluster_id`, `timestamp_hour`, `temperature_2m`, `relative_humidity_2m`, `precipitation`, `rain`, `snowfall`, `snow_depth`, `wind_speed_10m`, `cloud_cover`).
16. **`database_schema.png`**: Relational database entity-relationship (ERD) schema diagram illustrating table relationships.
17. **`raw_documents/`**: Original PKP PLK infrastructure source documents, including Temporary Speed Restriction (TSR / WOS) files, Track Closures (SHZT) statements, and railway line kilometrage maps.

---

## Academic disclaimer and terms of use

This dataset is compiled solely for non-commercial academic research, scientific benchmarking, and educational purposes. All underlying operational logs consist of public factual railway movement measurements.

Researchers interested in reconstructing the full underlying PostgreSQL relational schema (including `train_services`, `stations`, `occupancies`, and relational views) can consult the open-source pipeline repository:  
[marekk13/PKP-Intercity-Train-Delay-Scraper](https://github.com/marekk13/PKP-Intercity-Train-Delay-Scraper).

---

## Citation and metadata

```bibtex
@dataset{pkp_intercity_delays_2026,
  author       = {Marek Kostrz},
  title        = {{PKP Intercity train delays dataset}},
  month        = jul,
  year         = 2026,
  publisher    = {Zenodo },
  url          = {https://github.com/marekk13/PKP-Intercity-Train-Delay-Scraper}
}
```

## License

This dataset is distributed under the **Creative Commons Attribution 4.0 International (CC-BY 4.0)** license.
