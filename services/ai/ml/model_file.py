"""Load LightGBM artifacts when the checkout path contains non-ASCII text.

Some Windows LightGBM builds pass model_file through a narrow C API and fail
to open a valid Unicode path. Copying the small checked-in artifact to the
ASCII system temporary directory avoids changing the model or predictions.
"""
from pathlib import Path
import shutil
import tempfile
import lightgbm as lgb


def load_booster(path: Path) -> lgb.Booster:
    path = Path(path)
    if str(path).isascii():
        return lgb.Booster(model_file=str(path))
    with tempfile.TemporaryDirectory(prefix='turkisib-model-') as directory:
        target = Path(directory) / path.name
        if not str(target).isascii():
            raise OSError('An ASCII temporary directory is required for LightGBM')
        shutil.copyfile(path, target)
        return lgb.Booster(model_file=str(target))
