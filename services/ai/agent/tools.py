import json
from copy import deepcopy
from urllib.parse import quote
import httpx
import logging
from functools import lru_cache
from jsonschema import validate
from ..settings import SERVICE, settings
from ..api.schemas import State, Incident

EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
TRAIN = {'type': 'object', 'properties': {'train_id': {'type': 'string', 'maxLength': 80}}, 'required': ['train_id'], 'additionalProperties': False}
INCIDENT_SCHEMA = Incident.model_json_schema()
WHATIF_SCHEMA = {'type': 'object', 'properties': {'incident': INCIDENT_SCHEMA},
                 '$defs': INCIDENT_SCHEMA.pop('$defs', {}), 'required': ['incident'], 'additionalProperties': False}
SPECS = {
    'get_plan': ('Текущий план и его метрики', EMPTY),
    'get_index': ('Индекс качества и вклад факторов', EMPTY),
    'get_train_status': ('Состояние конкретного поезда', TRAIN),
    'list_trains': ('Список поездов', EMPTY),
    'get_forecast': ('Прогноз прокси-риска; не подтверждённый конфликт', {'type': 'object', 'properties': {'train_id': {'type': 'string'}}, 'additionalProperties': False}),
    'get_schedule_forecast': ('Учебная модель KZ: время целого перегона по синтетическому расписанию. Не реальные задержки.', TRAIN),
    'get_advice': ('Консультативный профиль скорости из солвера', TRAIN),
    'get_incidents': ('Зарегистрированные инциденты', EMPTY),
    'run_whatif': ('Песочница; не меняет живое состояние. Длительность задаётся incident.params.minutes.', WHATIF_SCHEMA),
}


def tool_schemas():
    return [{'name': name, 'description': desc, 'input_schema': schema} for name, (desc, schema) in SPECS.items()]


@lru_cache
def schedule_model():
    from ..ml.kz_schedule import ScheduleForecaster
    return ScheduleForecaster()


class Tools:
    def __init__(self, forecaster, config=settings, snapshot=None):
        self.forecaster = forecaster
        self.config = config
        self.snapshot = snapshot

    def fixture(self, name):
        return json.loads((SERVICE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))

    async def call(self, name, args):
        if name not in SPECS:
            return {'error': 'unknown_tool'}
        logging.getLogger('ai.tools').info('tool=%s mode=%s', name, 'fixture' if self.config.use_fixtures else 'api')
        try:
            validate(args, SPECS[name][1])
            data = await self._call(name, args)
            if name == 'get_forecast' and isinstance(data, list):
                data = [dict(row, display={'expected_delay_min': round(row['expected_delay_s'] / 60, 2),
                                          'proxy_probability_percent': round(row['p_conflict_15m'] * 100, 2)}) for row in data]
            return {'source': 'demo_snapshot' if self.snapshot is not None else ('fixture' if self.config.use_fixtures else 'api'), 'data': data}
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            # Do not expose HTTP exception text, headers, credentials or upstream bodies.
            return {'error': 'tool_unavailable', 'tool': name}
        except Exception as exc:
            from jsonschema.exceptions import ValidationError
            if isinstance(exc, ValidationError):
                return {'error': 'invalid_tool_arguments', 'tool': name}
            raise

    async def _call(self, name, args):
        if name == 'get_schedule_forecast':
            if self.snapshot is None:return {'error':'snapshot_required'}
            return [r for r in schedule_model().forecast(self.snapshot) if r['train_id']==args['train_id']]
        if self.snapshot is not None:
            state = self.snapshot.model_dump(mode='json')
            if name == 'list_trains': return state['trains']
            if name == 'get_train_status':
                return next((t for t in state['trains'] if t['train_id'] == args['train_id']), {'error': 'train_not_found'})
            if name == 'get_forecast':
                results = self.forecaster.forecast(self.snapshot)
                return [r for r in results if not args.get('train_id') or r['train_id'] == args['train_id']]
            return {'error': 'not_computed_for_demo_snapshot', 'reason': 'Для отредактированного сценария доступны состояние поездов и прогноз ML. План, индекс и оптимизация не рассчитывались.'}
        if self.config.use_fixtures:
            state = self.fixture('state')
            if name == 'get_plan': return self.fixture('plan')
            if name == 'get_index': return self.fixture('index')
            if name == 'get_incidents': return self.fixture('incidents')
            if name == 'list_trains': return state['trains']
            if name == 'get_train_status':
                return next((t for t in state['trains'] if t['train_id'] == args['train_id']), {'error': 'train_not_found'})
            if name == 'get_advice':
                return self.fixture('advice').get(args['train_id'], {'error': 'advice_not_available'})
            if name == 'get_forecast':
                results = self.forecaster.forecast(State.model_validate(state))
                return [r for r in results if not args.get('train_id') or r['train_id'] == args['train_id']]
            if name == 'run_whatif':
                incident = Incident.model_validate(args['incident'])
                example = self.fixture('whatif')
                # Never return the same precomputed figures for arbitrary incidents.
                if incident.kind != 'block_closed' or incident.target_id not in ['Б-В', 'B-C'] or incident.params.minutes != 20:
                    return {'error': 'fixture_scenario_not_available', 'supported': 'Б-В, закрытие на 20 минут'}
                return deepcopy(example)
        async with httpx.AsyncClient(timeout=8) as client:
            platform, solver = self.config.platform_url, self.config.solver_url
            if name == 'run_whatif':
                snapshot = (await self._get(client, platform + '/state'))
                r = await client.post(solver + '/whatif', json={'state': snapshot, 'incident': args['incident']})
            elif name == 'get_forecast':
                state = State.model_validate(await self._get(client, platform + '/state'))
                result = self.forecaster.forecast(state)
                return [r for r in result if not args.get('train_id') or r['train_id'] == args['train_id']]
            elif name == 'get_advice':
                state = await self._get(client, platform + '/state')
                r = await client.post(solver + '/advice', json={'state': state, 'train_id': args['train_id']})
            else:
                paths = {'get_plan': '/plan', 'get_index': '/index', 'list_trains': '/trains',
                         'get_incidents': '/incidents', 'get_train_status': '/trains/' + quote(args.get('train_id', ''), safe='')}
                r = await client.get(platform + paths[name])
            r.raise_for_status()
            return r.json()

    @staticmethod
    async def _get(client, url):
        r = await client.get(url)
        r.raise_for_status()
        return r.json()
