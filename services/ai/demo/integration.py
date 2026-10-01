"""Adapt one immutable dispatcher snapshot for the checked-in platform planner.

This is an advisory bridge. The timetable playback remains the source of the
visible state, and the planner never changes it.
"""
from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import json
import math

from backend.planner.fifo import plan_fifo
from backend.validator.resources import validate_human_decision, validate_plan
from .simulation import BASE, geometry, snapshot


@lru_cache(maxsize=1)
def _template():
    from backend.simulator import Simulator
    return Simulator('SCN-ALL').snapshot().to_dict()


def platform_snapshot(demo: dict, seed: int) -> dict:
    """Map the same visible SIM positions and closures to ScenarioSnapshot v1."""
    template = deepcopy(_template())
    geo = geometry()
    service_by_id = {row['train_id']: row for row in geo['services']}
    state_by_id = {row['train_id']: row for row in demo['state']['trains']}
    blocks_by_id = {row['id']: row for row in demo['state']['infra']['blocks']}
    geo_by_id = {row['properties']['id']: row['properties'] for row in geo['features']}
    final_arrival = {}
    for row in geo['timetable']:
        if row['scheduled_arrival']:
            final_arrival[row['train_id']] = max(final_arrival.get(row['train_id'], ''), row['scheduled_arrival'])
    if set(state_by_id) != {row['train_id'] for row in template['trains']}:
        raise ValueError('demo and platform train sets differ')
    template.update(scenario_id='KZ-DEMO-ADVISORY', seed=seed,
                    virtual_time=demo['ts'], version=round(demo['elapsed_s'] * 1000),
                    source_type='SIMULATED_DEMO', active_incidents=[])
    for block in template['blocks']:
        observed = blocks_by_id[block['block_id']]
        block['closed'] = observed['closed']
        block['occupied_by'] = next((row['train_id'] for row in state_by_id.values()
                                     if row['position']['block_id'] == block['block_id']), None)
    at = datetime.fromisoformat(demo['ts'])
    for train in template['trains']:
        observed = state_by_id[train['train_id']]
        if at < datetime.fromisoformat(train['planned_start']):
            train.update(block_index=-1, block_id=None, progress=0., status='scheduled',
                         delay_min=observed['delay_s'] / 60, hold_until=None)
            continue
        if train['train_id'] in final_arrival and at >= datetime.fromisoformat(final_arrival[train['train_id']]):
            train.update(block_index=len(train['route']) - 1, block_id=None, progress=1.,
                         status='completed', delay_min=observed['delay_s'] / 60, hold_until=None)
            continue
        block_id = observed['position']['block_id']
        if block_id not in train['route']:
            raise ValueError(f'{train["train_id"]} is outside its route')
        index = train['route'].index(block_id)
        block_length = geo_by_id[block_id]['length_km']
        progress = observed['position']['km'] / block_length
        if service_by_id[train['train_id']]['direction'] != 'forward':
            progress = 1 - progress
        train.update(block_index=index, block_id=block_id,
                     progress=max(0., min(1., progress)),
                     delay_min=observed['delay_s'] / 60,
                     status='moving', hold_until=None)
    if demo['incident_active'] and demo['incident'] in ('closure', 'chaos'):
        at = (BASE + timedelta(seconds=demo['elapsed_s'])).isoformat()
        remaining = max(1, math.ceil((demo['incident_end_s'] - demo['elapsed_s']) / 60))
        for block in template['blocks']:
            if block['closed']:
                template['active_incidents'].append({
                    'incident_id': f'UI-{block["block_id"]}', 'type': 'BLOCK_CLOSURE',
                    'block_id': block['block_id'], 'at': at, 'duration_min': remaining,
                })
    return template


def _pair_ids(demo: dict) -> list[str]:
    pool = [row for row in demo['display'] if row['origin'] == 'KOK' or row['destination'] == 'KOK']
    return [next(row['train_id'] for row in pool if row['direction'] == direction)
            for direction in (1, -1)]


def _snapshot_id(demo: dict) -> str:
    canonical = json.dumps(demo, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]


def check_decision(elapsed: float, incident: str, incident_at: float,
                   seed: int, choice: str) -> dict:
    """Validate the game's proposed action without applying it to playback."""
    if choice not in ('A', 'B', 'C'):
        raise ValueError('unknown choice')
    demo = snapshot(float(elapsed), incident, float(incident_at))
    platform = platform_snapshot(demo, seed)
    pair_ids = _pair_ids(demo)
    actions = []
    for index, train_id in enumerate(pair_ids):
        grant = choice == ('A' if index == 0 else 'B')
        decision = {'train_id': train_id,
                    'action': 'GRANT_ENTRY' if grant else 'HOLD_TRAIN',
                    'snapshot_version': platform['version']}
        checked = validate_human_decision(platform, decision)
        actions.append({'train_id': train_id, 'action': decision['action'],
                        'accepted': checked.valid,
                        'issue_codes': [issue.code for issue in checked.issues]})
    return {'snapshot_id': _snapshot_id(demo), 'snapshot_time': demo['ts'],
            'choice': choice, 'actions': actions,
            'accepted': all(row['accepted'] for row in actions),
            'applied': False, 'source': demo['source']}


def analyze(elapsed: float, incident: str, incident_at: float, seed: int,
            *, solve: bool = True, time_limit_seconds: float = 2.0) -> dict:
    demo = snapshot(float(elapsed), incident, float(incident_at))
    snapshot_id = _snapshot_id(demo)
    occupancy = defaultdict(list)
    for train in demo['state']['trains']:
        occupancy[train['position']['block_id']].append(train['train_id'])
    overlaps = [{'block_id': block_id, 'train_ids': train_ids}
                for block_id, train_ids in occupancy.items() if len(train_ids) > 1]
    platform = platform_snapshot(demo, seed)
    pair_ids = _pair_ids(demo)
    pair = deepcopy(platform)
    pair['trains'] = [train for train in platform['trains'] if train['train_id'] in pair_ids]
    fifo = plan_fifo(pair)
    result = {
        'snapshot_id': snapshot_id, 'snapshot_time': demo['ts'],
        'elapsed_s': elapsed, 'incident': incident, 'incident_at_s': incident_at,
        'seed': seed, 'source': demo['source'],
        'pair_train_ids': pair_ids,
        'snapshot_overlaps': overlaps,
        'fifo': {'status': fifo['status'], 'ordered_train_ids': fifo['ordered_train_ids'],
                 'limitations': fifo['limitations']},
        'cp_sat': {'status': 'NOT_REQUESTED', 'valid': None, 'reservations': []},
        'full_cp_sat': {'status': 'NOT_REQUESTED'},
        'scope': 'two_train_advisory_block_plan',
        'limitations': [
            'The map keeps its timetable playback; the plan is never applied.',
            'FIFO is an order only, so delay and energy savings are not comparable.',
            'The checked pair plan excludes the other 26 trains and their reservations.',
            'Station dwell and energy are not modeled by this block-only plan.',
        ],
    }
    if not solve:
        return result
    if incident in ('restriction', 'chaos'):
        result['cp_sat'] = {'status': 'UNSUPPORTED_SCENARIO', 'valid': None,
                            'reason': 'Speed restrictions and chaos delays are not encoded in this planner adapter.',
                            'reservations': []}
        return result
    try:
        from backend.planner.cp_sat import plan_snapshot
        full = plan_snapshot(platform, time_limit_seconds=time_limit_seconds)
        result['full_cp_sat'] = {'status': full['status'], 'reservation_count': len(full.get('reservations', []))}
        if full['status'] in ('OPTIMAL', 'FEASIBLE'):
            result['full_cp_sat']['valid'] = validate_plan(platform, full).valid
        plan = plan_snapshot(pair, time_limit_seconds=time_limit_seconds)
    except (RuntimeError, ImportError) as exc:
        result['cp_sat'] = {'status': 'UNAVAILABLE', 'valid': None,
                            'reason': str(exc), 'reservations': []}
        return result
    if plan['status'] in ('OPTIMAL', 'FEASIBLE'):
        checked = validate_plan(pair, plan).to_dict()
        plan['valid'] = checked['valid']
        plan['validation_issues'] = checked['issues'][:10]
    result['cp_sat'] = {
        'status': plan['status'], 'valid': plan.get('valid'),
        'reason': plan.get('reason'),
        'solver_wall_time_seconds': plan.get('solver_wall_time_seconds'),
        'reservation_count': len(plan.get('reservations', [])),
        'validation_issues': plan.get('validation_issues', []),
        'reservations': plan.get('reservations', []),
        'scope': plan.get('scope', 'BLOCK_ONLY'),
    }
    return result
