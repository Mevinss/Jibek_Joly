import json
import pytest
from services.ai.scripts.sync_main_data import blob_sha, checked_path
from services.ai.training.train import input_provenance, resolve_data_dir
from services.ai.ml.infer import Forecaster
from services.ai.api.schemas import State
from services.ai.settings import SERVICE


def test_source_paths_cannot_escape_snapshot(tmp_path):
    for path in ['../escape', '/absolute', r'..\escape', 'C:/outside']:
        with pytest.raises(ValueError): checked_path(tmp_path, path)
    assert checked_path(tmp_path, 'data/x.csv') == tmp_path / 'data/x.csv'


def test_provenance_rejects_changed_training_input(tmp_path):
    base = tmp_path / 'data/external/pkp/dataset'
    entries = []
    for name in ['processed_tabular/train_delays_tabular.parquet', 'raw/run_stops.csv',
                 'graph_and_sequences/splits.json', 'README.md']:
        path = base / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'verified input')
        entries.append({'path': path.relative_to(tmp_path).as_posix(), 'sha': blob_sha(path.read_bytes())})
    (tmp_path/'tree.json').write_text(json.dumps({'sha':'tree1','tree':entries}))
    (tmp_path/'snapshot.json').write_text(json.dumps({'commit':'commit1','tree_sha':'tree1'}))
    assert input_provenance(base, 'commit1')['commit'] == 'commit1'
    (base/'raw/run_stops.csv').write_bytes(b'changed input')
    with pytest.raises(ValueError, match='Input differs'): input_provenance(base, 'commit1')


def test_explicit_missing_dataset_never_silently_uses_old_data(tmp_path):
    with pytest.raises(FileNotFoundError): resolve_data_dir(tmp_path)


def test_alert_uses_loaded_artifact_threshold():
    model = Forecaster()
    state = State.model_validate(json.loads((SERVICE/'fixtures/state.json').read_text(encoding='utf-8')))
    assert model.reg is not None
    model.threshold = 1.0
    model.config['alert_threshold'] = 0.0
    results = model.forecast(state)
    assert all(not row['alert'] for row in results if not row['degraded'])
    assert all(row['alert'] for row in results if row['degraded'])
