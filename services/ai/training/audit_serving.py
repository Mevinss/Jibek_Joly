"""Recompute evidence without changing the existing delay/proxy artifacts."""
import json
import time
import numpy as np
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold
from sklearn.linear_model import LinearRegression
from .train import prepare, stats_from, transform, dump, classification
from .train_kz_schedule import rows, FEATURES as KZ_FEATURES
from ..ml.features import FEATURES
from ..settings import SERVICE, ROOT


def main():
    data, split = prepare()
    parts = [data[data.run_id.isin([int(k) for k, v in split.items() if v == name])] for name in ('train', 'val', 'test')]
    train, val, test = parts
    assert all(not set(a.run_id) & set(b.run_id) for a, b in [(train,val),(train,test),(val,test)])
    stats = stats_from(train)
    xt, xv, xs = [transform(p, stats) for p in parts]
    model_dir = SERVICE / 'models/forecast_main'
    reg = lgb.Booster(model_file=str(model_dir/'reg.txt'))
    pred = reg.predict(xs, num_threads=1)
    buckets = []
    for name, lo, hi in [('all',0,np.inf),('0–3',0,3),('3–10',3,10),('10+',10,np.inf)]:
        m = (test.prev_delay_departure_min >= lo) & (test.prev_delay_departure_min < hi)
        y = test.delta_delay.to_numpy()[m]
        buckets.append(dict(bucket=name,n=int(m.sum()),model=float(np.abs(y-pred[m]).mean()),zero=float(np.abs(y).mean()),p50=float(np.abs(y-xs.edge_delta_delay_P50.to_numpy()[m]).mean())))
    # Marginal residual quantiles from validation, never the test labels.
    residual = val.delta_delay.to_numpy()-reg.predict(xv,num_threads=1)
    quantiles = np.quantile(residual,[.1,.5,.9])
    coverage = float(np.mean((test.delta_delay >= pred+quantiles[0]) & (test.delta_delay <= pred+quantiles[2])))
    # New, separately named classifier for the requested PURE delay-growth target.
    # Omit outcome-based statistics entirely so training rows cannot leak through them.
    growth_features = FEATURES[:-5]
    clf = lgb.LGBMClassifier(n_estimators=180,num_leaves=15,min_child_samples=100,learning_rate=.05,random_state=42,n_jobs=2,verbosity=-1)
    clf.fit(xt[growth_features],(train.delta_delay>=3).astype(int))
    ids=sorted(val.run_id.unique()); cm=val.run_id.isin(ids[::2]).to_numpy()
    raw=clf.predict_proba(xv[growth_features])[:,1]
    cal=IsotonicRegression(out_of_bounds='clip').fit(raw[cm],(val.delta_delay>=3).to_numpy()[cm])
    probs=cal.predict(clf.predict_proba(xs[growth_features])[:,1])
    out=SERVICE/'models/advisory'; out.mkdir(exist_ok=True)
    clf.booster_.save_model(str(out/'growth.txt'))
    bounds={f:dict(min=float(xt[f].min()),max=float(xt[f].max())) for f in FEATURES}
    dump(out/'serving.json',dict(version='pkp-advisory-v2',features=growth_features,bounds=bounds,residual_quantiles_min=quantiles.tolist(),interval_semantics='marginal validation residual P10/P50/P90; not conditional, not calibrated for Kazakhstan',test_interval_coverage=coverage,calibration=dict(x=cal.X_thresholds_.tolist(),y=cal.y_thresholds_.tolist()),growth_metrics=classification((test.delta_delay>=3).astype(int),probs,.1)))
    # Actual, held-out run replay (most stops; deterministic tie break).
    run_id=int(test.groupby('run_id').size().sort_values(ascending=False,kind='stable').index[0])
    ordered=test.assign(predicted=pred).query('run_id == @run_id').sort_values('stop_order')
    replay=[dict(stop=int(r.stop_order),actual=float(r.delta_delay),predicted=float(r.predicted),previous_delay=float(r.prev_delay_departure_min)) for r in ordered.itertuples()]
    # Formula + residual against completely unseen segments.
    kz=rows(ROOT/'data/kz_demo/KZ'); kz['base']=kz.distance_km/kz.speed_limit_kmh*60
    diagnostics=[]
    for a,b in GroupKFold(n_splits=4).split(kz,groups=kz.segment_id):
        design=lambda d: np.column_stack([d['base'],np.ones(len(d)),d.category_code,d.direction])
        formula=LinearRegression(fit_intercept=False).fit(design(kz.iloc[a]),kz.target.iloc[a])
        base_train=formula.predict(design(kz.iloc[a])); base_test=formula.predict(design(kz.iloc[b]))
        residual_model=lgb.LGBMRegressor(n_estimators=80,num_leaves=5,min_child_samples=8,verbosity=-1,n_jobs=1,random_state=42)
        residual_model.fit(kz[KZ_FEATURES].iloc[a],kz.target.iloc[a]-base_train)
        residual_pred=base_test+residual_model.predict(kz[KZ_FEATURES].iloc[b])
        diagnostics.append(dict(held_segments=sorted(kz.segment_id.iloc[b].unique()),n=len(b),formula_mae=float(np.abs(kz.target.iloc[b]-base_test).mean()),residual_mae=float(np.abs(kz.target.iloc[b]-residual_pred).mean())))
    durations=[]
    for _ in range(110):
        start=time.perf_counter(); reg.predict(xs.iloc[:28],num_threads=1); durations.append((time.perf_counter()-start)*1000)
    report=dict(version='pkp-advisory-v2',buckets=buckets,growth_metrics=classification((test.delta_delay>=3).astype(int),probs,.1),interval_coverage=coverage,residual_quantiles_min=quantiles.tolist(),replay=dict(run_id=run_id,source='held-out PKP; stop order, no absolute dates',points=replay),kz_group_folds=diagnostics,latency_28_regression_ms=dict(p50=float(np.percentile(durations[10:],50)),p95=float(np.percentile(durations[10:],95))),shap=json.loads((model_dir/'shap_importance.json').read_text()),model_info=json.loads((model_dir/'metrics.json').read_text(encoding='utf-8')))
    dump(SERVICE/'web/evidence.json',report);dump(SERVICE/'reports/serving_audit.json',report)
    print(json.dumps(dict(buckets=buckets,coverage=coverage,kz=diagnostics,latency=report['latency_28_regression_ms']),indent=2))


if __name__=='__main__': main()
