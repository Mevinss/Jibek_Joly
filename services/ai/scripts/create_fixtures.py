"""Small, explicitly fictional API fixtures; these are NOT optimizer benchmarks."""
from pathlib import Path
import json

BASE = Path(__file__).resolve().parents[1] / 'fixtures'


def main():
    BASE.mkdir(exist_ok=True)
    stamp = '2026-10-01T10:00:00+05:00'
    trains = [dict(train_id=str(1001+i), type=['пасс', 'скоростной', 'груз'][i % 3],
                   priority=[2, 3, 1][i % 3], position={'block_id': ['А-Б', 'Б-В'][i % 2], 'km': i},
                   speed=60, delay_s=(i % 5)*120, ts=stamp,
                   min_technical_time_min=10, time_reserve_min=2) for i in range(25)]
    state = dict(trains=trains, infra={'blocks': [dict(id=b, occupied=True, closed=False, speed_limit=100) for b in ['А-Б', 'Б-В']], 'signals': [], 'switches': []})
    data = {'state': state,
            'plan': {'plan_id': 'fixture-plan', 'profile': 'balance', 'slots': [], 'conflicts': [], 'metrics': {'total_delay_s': 600, 'energy_kwh': 120}},
            'index': {'score': 76, 'grade': 'C', 'category': 'Внимание', 'factors': [{'name': 'Расписание', 'weight': .4, 'value': .6, 'contribution': 24}]},
            'incidents': [{'id': 'incident-demo', 'kind': 'delay', 'target_id': '1002', 'params': {'minutes': 2}, 'ts': stamp}],
            'advice': {'1001': {'train_id': '1001', 'segments': [{'from_km': 0, 'to_km': 10, 'v_recommend': 60, 'v_limit': 100}], 'eta': stamp, 'energy_kwh': 20}},
            'whatif': {'scenario_id': 'fixture-B-C-20', 'notice': 'Подготовленные фикстуры интеграционного контракта; не результаты оптимизации.',
                       'incident': {'id': 'whatif-demo', 'kind': 'block_closed', 'target_id': 'Б-В', 'params': {'minutes': 20}, 'ts': stamp},
                       'variants': [{'label': label, 'profile': profile,
                                     'plan': {'plan_id': 'fixture-'+label, 'metrics': {'total_delay_s': delay, 'energy_kwh': energy}},
                                     'index': {'score': score}, 'recalc_ms': None} for label, profile, delay, energy, score in
                                    [('A', 'min_delay', 720, 150, 70), ('B', 'balance', 900, 130, 74), ('C', 'min_energy', 1200, 110, 68)]]}}
    for name, value in data.items():
        (BASE / (name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
