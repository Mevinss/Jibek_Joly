"""Single feature order shared by training and serving. No target-derived IDs."""
from collections import Counter
import math
import pandas as pd

FEATURES = [
    'train_kind', 'prev_delay_departure_min', 'time_reserve_min',
    'min_technical_time_min', 'hour_sin', 'hour_cos', 'day_of_week',
    'is_track_closure', 'is_speed_warning', 'active_disruption_group',
    'num_platform_tracks', 'is_passing_loop', 'is_node',
    'edge_delta_delay_P50', 'edge_delta_delay_P90', 'edge_delta_delay_MAD',
    'station_delta_stop_min_P50', 'station_delta_stop_min_P90',
]
CATEGORICAL = ['train_kind', 'active_disruption_group']
TYPES = {'EIP': 1, 'скоростной': 1, 'high_speed': 1, 'EIC': 0, 'IC': 0,
         'TLK': 0, 'пасс': 0, 'пассажирский': 0, 'passenger': 0}


def disruption_group(code):
    code = int(code)
    groups = [{1, 2, 3, 4, 15, 24, 26, 43}, {9, 23, 31, 42}, {10, 16, 28},
              {30}, {14, 18, 19, 35}, {5, 6, 7, 34, 36, 39}]
    if code == 0:
        return 0
    return next((i + 1 for i, group in enumerate(groups) if code in group), 7)


def serving_frame(state, profiles):
    blocks = {b.id: b for b in state.infra.blocks}
    loads = Counter(t.position.block_id for t in state.trains)
    rows, degraded = [], []
    for t in state.trains:
        b = blocks.get(t.position.block_id)
        profile = profiles.get(t.position.block_id, profiles.get('default', {}))
        hour = t.ts.hour + t.ts.minute / 60
        row = dict(profile)
        row.update(train_kind=TYPES.get(t.type, 0), prev_delay_departure_min=t.delay_s / 60,
                   time_reserve_min=t.time_reserve_min, min_technical_time_min=t.min_technical_time_min,
                   hour_sin=math.sin(hour * math.tau / 24), hour_cos=math.cos(hour * math.tau / 24),
                   day_of_week=t.ts.weekday(), block_load=(b.block_load if b and b.block_load is not None else loads[t.position.block_id]),
                   is_track_closure=int(b.closed) if b else 0, is_speed_warning=int(b.speed_limit < 100) if b else 0,
                   active_disruption_group=b.active_disruption_group if b else 0,
                   num_platform_tracks=b.num_platform_tracks if b else 2,
                   is_passing_loop=int(b.is_passing_loop) if b else 0, is_node=int(b.is_node) if b else 0)
        rows.append({f: row.get(f, 0) for f in FEATURES})
        degraded.append(t.type not in TYPES or b is None)
    return pd.DataFrame(rows, columns=FEATURES).astype(float), degraded
