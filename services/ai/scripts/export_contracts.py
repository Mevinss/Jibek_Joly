"""Initial proposed schemas: coordinate changes with all service owners in the PR."""
from ..api.schemas import Forecast, State, Incident, ChatRequest
from ..settings import ROOT
import json


def main():
    folder = ROOT / 'contracts'
    folder.mkdir(exist_ok=True)
    for name, model in [('Forecast', Forecast), ('State', State), ('Incident', Incident), ('ChatRequest', ChatRequest)]:
        schema = model.model_json_schema()
        schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
        (folder / (name+'.schema.json')).write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
