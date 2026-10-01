"""Optional advisory contract: legacy forecasts remain unchanged."""
import json
import numpy as np
import yaml
from ..settings import SERVICE
from .features import serving_frame
from .model_file import load_booster


class Advisory:
    def __init__(self, forecaster):
        self.base = forecaster
        self.config = yaml.safe_load((SERVICE/'config/advisory.yaml').read_text())
        path = SERVICE / 'models/advisory'
        self.meta = json.loads((path/'serving.json').read_text())
        self.growth = load_booster(path/'growth.txt')

    def forecast(self, state):
        if not state.trains:
            return []
        frame, degraded = serving_frame(state, self.base.profiles)
        if self.base.reg is None:
            return [dict(train_id=t.train_id, reliable=False, reasons=['model_unavailable']) for t in state.trains]
        delta=self.base.reg.predict(frame,num_threads=1)
        raw=self.growth.predict(frame[self.meta['features']],num_threads=1)
        p=np.interp(raw,self.meta['calibration']['x'],self.meta['calibration']['y'])
        q=self.meta['residual_quantiles_min']
        result=[]
        for i,t in enumerate(state.trains):
            outside=[f for f,b in self.meta['bounds'].items() if frame.iloc[i][f]<b['min']-1e-8 or frame.iloc[i][f]>b['max']+1e-8]
            reasons=outside+(['unsupported_train'] if degraded[i] else [])
            # Kazakhstan is an unvalidated domain even with numerically in-range features.
            if t.source_domain=='kz_synthetic': reasons.append('unvalidated_kazakhstan')
            if t.next_block_closed and t.deterministic_wait_s is None: reasons.append('unknown_reopening')
            valid=not reasons
            deterministic=t.delay_s/60+(t.deterministic_wait_s or 0)/60+t.restriction_extra_s/60
            intervals=[max(0,deterministic+float(delta[i])+r) for r in q] if valid else None
            result.append(dict(train_id=t.train_id,reliable=valid,ood_features=outside,reasons=reasons,
                current_delay_min=t.delay_s/60,known_wait_min=None if t.deterministic_wait_s is None else t.deterministic_wait_s/60,
                restriction_extra_min=t.restriction_extra_s/60,deterministic_min=deterministic,
                ml_delta_min=float(delta[i]) if valid else None,delay_interval_min=intervals,
                delay_growth_probability=float(p[i]) if valid else None,
                risk_semantics='delta_delay_ge_3_next_segment',interval_semantics=self.meta['interval_semantics'],
                solver_buffer_s=self.config['solver_buffer_k']*max(0,intervals[2]-intervals[1])*60 if valid else None,
                model_version=self.meta['version']))
        return result
