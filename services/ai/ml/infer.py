from pathlib import Path
import json
import numpy as np
import yaml
from .features import FEATURES, serving_frame
from ..settings import SERVICE


class Forecaster:
    def __init__(self, model_dir: Path | None = None):
        self.config = yaml.safe_load((SERVICE / 'config/forecast.yaml').read_text(encoding='utf-8'))
        self.model_dir = model_dir or SERVICE / 'models' / self.config.get('model_directory', 'forecast_v1')
        self.labels = yaml.safe_load((SERVICE / 'config/feature_labels_ru.yaml').read_text(encoding='utf-8'))
        self.profiles = {}
        self.reg = self.clf = None
        self.info = {'model_version': 'rule_fallback', 'accepted': False, 'warning':
                     'Эвристическая оценка; вероятность не калибрована. Не заменяет СЦБ.'}
        try:
            import lightgbm as lgb
            metadata = json.loads((self.model_dir / 'features.json').read_text())
            if metadata['features'] != FEATURES:
                raise ValueError('Feature order mismatch')
            info = json.loads((self.model_dir / 'metrics.json').read_text(encoding='utf-8'))
            lookup = json.loads((self.model_dir / 'lookup_edge_stats.json').read_text())
            mapping = yaml.safe_load((SERVICE / 'config/block_profiles.yaml').read_text(encoding='utf-8'))
            self.profiles = {block: lookup['profiles'][profile] for block, profile in mapping.items()}
            self.calibration = json.loads((self.model_dir / 'calibrator.json').read_text())
            if not info['accepted']:
                raise ValueError('Model failed baseline acceptance gate')
            self.reg = lgb.Booster(model_file=str(self.model_dir / 'reg.txt'))
            self.clf = lgb.Booster(model_file=str(self.model_dir / 'clf.txt'))
            self.info = info
            self.threshold = float(info['threshold'])
        except Exception:
            # Corrupt native model files must not prevent advisory service startup.
            self.reg = self.clf = None

    def forecast(self, state):
        if not state.trains:
            return []
        frame, degraded = serving_frame(state, self.profiles)
        n = len(frame)
        delay = np.zeros(n)
        probability = np.zeros(n)
        impacts = np.zeros((n, len(FEATURES)))
        if self.reg is not None:
            delay = self.reg.predict(frame, num_threads=1)
            raw = self.clf.predict(frame, num_threads=1)
            probability = np.interp(raw, self.calibration['x'], self.calibration['y'])
            impacts = self.clf.predict(frame, pred_contrib=True, num_threads=1)[:, :-1]
        result = []
        for i, t in enumerate(state.trains):
            fallback = self.reg is None or degraded[i]
            if fallback:
                # Scores are deliberately identified as rules, never validated ML probabilities.
                p = min(.95, .05 + min(t.delay_s / 3600, .6) + .03 * max(0, 4 - t.priority))
                expected = t.delay_s
                top = [{'name': 'Текущее опоздание (правило)', 'impact': round(min(t.delay_s / 3600, .6), 4)}]
            else:
                p = float(probability[i])
                expected = max(0, t.delay_s / 60 + float(delay[i])) * 60
                indices = np.argsort(np.abs(impacts[i]))[-3:][::-1]
                top = [{'name': self.labels.get(FEATURES[j], FEATURES[j]), 'impact': round(float(impacts[i, j]), 5)} for j in indices]
            result.append(dict(train_id=t.train_id, p_conflict_15m=round(p, 6),
                               expected_delay_s=round(expected, 2), top_features=top,
                               model_version='rule_fallback' if fallback else self.info['model_version'],
                               horizon_min=None, horizon_semantics='next_segment_proxy_not_validated_15m',
                               alert=p >= (self.config['alert_threshold'] if fallback else self.threshold), degraded=fallback))
        return result
