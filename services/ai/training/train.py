"""Reproducible grouped benchmark; real PKP passenger data, proxy conflict labels."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import time
import numpy as np
import pandas as pd
import lightgbm as lgb
import yaml
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupKFold
from sklearn.metrics import (mean_absolute_error, mean_squared_error, r2_score,
                             roc_auc_score, average_precision_score, brier_score_loss,
                             precision_recall_curve, precision_score, recall_score)
from ..settings import ROOT, SERVICE
from ..ml.features import FEATURES, CATEGORICAL, disruption_group

STAT_COLS = FEATURES[-5:]


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=lambda x: x.item() if hasattr(x, 'item') else str(x), allow_nan=False), encoding='utf-8')


def prepare():
    base = next((ROOT / 'data/pkp').rglob('train_delays_tabular.parquet')).parents[1]
    frame = pd.read_parquet(base / 'processed_tabular/train_delays_tabular.parquet').drop_duplicates()
    raw = pd.read_csv(base / 'raw/run_stops.csv')
    raw = raw.sort_values(['run_id', 'stop_order'])
    for col in ['scheduled_arrival', 'scheduled_departure']:
        raw[col] = pd.to_timedelta(raw[col], errors='coerce')
    raw['previous_departure'] = raw.groupby('run_id').scheduled_departure.shift()
    raw['scheduled_travel'] = ((raw.scheduled_arrival - raw.previous_departure).dt.total_seconds() / 60) % 1440
    raw['station_delta'] = raw.delay_departure_min - raw.delay_arrival_min
    keep = ['run_id', 'stop_order', 'scheduled_travel', 'previous_departure', 'station_delta']
    frame = frame.merge(raw[keep], on=['run_id', 'stop_order'], validate='one_to_one')
    frame = frame[(frame.is_prev_departure_delay_imputed == 0) & frame.delta_delay.notna() & frame.previous_departure.notna()].copy()
    frame['actual_travel'] = frame.scheduled_travel + frame.delta_delay
    frame['train_kind'] = (frame.category_code.astype(str) == 'EIP').astype(int)
    hour = frame.previous_departure.dt.total_seconds() / 3600
    frame['hour_sin'] = np.sin(hour * np.pi / 12)
    frame['hour_cos'] = np.cos(hour * np.pi / 12)
    frame['month'] = np.rint(np.arctan2(frame.month_sin, frame.month_cos) * 6 / np.pi).astype(int) % 12
    frame['active_disruption_group'] = frame.edge_active_difficulty_id.map(disruption_group)
    # Absolute run dates are NOT in the release. A +/-30-minute multi-run load
    # would accidentally pool different days; deliberately omit block_load from ML v1.
    config = yaml.safe_load((SERVICE / 'config/forecast.yaml').read_text())
    frame['proxy'] = ((frame.delta_delay >= config['proxy_delta_threshold_min']) | frame.difficulty_id.isin([5, 6, 7, 34, 36, 39])).astype(int)
    splits = json.loads(next(base.rglob('splits.json')).read_text())
    return frame.reset_index(drop=True), splits


def stats_from(train):
    grouped = train.groupby('segment_id', observed=True)
    edge = grouped.delta_delay.agg(['median', lambda x: x.quantile(.9), lambda x: np.median(np.abs(x - np.median(x)))])
    edge.columns = STAT_COLS[:3]
    station = train.groupby('station_id', observed=True).station_delta.agg(['median', lambda x: x.quantile(.9)])
    station.columns = STAT_COLS[3:]
    tech = train[train.actual_travel > 0].groupby('segment_id', observed=True).actual_travel.quantile(.01)
    return edge, station, tech


def transform(frame, stats):
    edge, station, tech = stats
    x = frame.copy()
    for col in edge:
        x[col] = x.segment_id.astype(str).map(edge[col]).astype(float).fillna(float(edge[col].median()))
    for col in station:
        x[col] = x.station_id.map(station[col]).astype(float).fillna(float(station[col].median()))
    x['min_technical_time_min'] = x.segment_id.astype(str).map(tech).astype(float).fillna(float(tech.median())).clip(lower=.1)
    x['time_reserve_min'] = (x.scheduled_travel - x.min_technical_time_min).clip(lower=0)
    return x[FEATURES].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0)


def matrices(train, val, test):
    stats = stats_from(train)
    xtrain = transform(train, stats)
    # Target-based statistics for training never include the row's run.
    folds = GroupKFold(n_splits=5)
    for a, b in folds.split(train, groups=train.run_id):
        xtrain.iloc[b] = transform(train.iloc[b], stats_from(train.iloc[a])).to_numpy()
    return xtrain, transform(val, stats), transform(test, stats), stats


def regression(y, pred):
    return dict(mae=float(mean_absolute_error(y, pred)), rmse=float(np.sqrt(mean_squared_error(y, pred))), r2=float(r2_score(y, pred)))


def classification(y, p, threshold):
    bins = np.linspace(0, 1, 11)
    ece, calibration = 0., []
    for i in range(10):
        mask = (p >= bins[i]) & ((p <= bins[i + 1]) if i == 9 else (p < bins[i + 1]))
        if mask.any():
            observed, predicted = float(np.mean(np.asarray(y)[mask])), float(np.mean(p[mask]))
            ece += mask.mean() * abs(observed - predicted)
            calibration.append({'predicted': predicted, 'observed': observed, 'count': int(mask.sum())})
    return dict(roc_auc=float(roc_auc_score(y, p)), pr_auc=float(average_precision_score(y, p)),
                brier=float(brier_score_loss(y, p)), ece=float(ece),
                precision=float(precision_score(y, p >= threshold, zero_division=0)),
                recall=float(recall_score(y, p >= threshold, zero_division=0)), calibration=calibration)


def fit(train, val, test, out, label):
    started = time.perf_counter()
    xt, xv, xs, stats = matrices(train, val, test)
    # Deterministic small search on validation; no test-dependent parameter selection.
    best = None
    for leaves in [15, 31]:
        params = dict(n_estimators=300, learning_rate=.05, num_leaves=leaves,
                      min_child_samples=80, random_state=42, n_jobs=4, verbosity=-1)
        model = lgb.LGBMRegressor(objective='regression_l1', **params)
        model.fit(xt, train.delta_delay, eval_set=[(xv, val.delta_delay)],
                  categorical_feature=CATEGORICAL, callbacks=[lgb.early_stopping(25, verbose=False)])
        score = mean_absolute_error(val.delta_delay, model.predict(xv))
        if best is None or score < best[0]: best = score, model, params
    reg, params = best[1:]
    clf = lgb.LGBMClassifier(objective='binary', scale_pos_weight=float((1-train.proxy.mean())/train.proxy.mean()), **params)
    clf.fit(xt, train.proxy, eval_set=[(xv, val.proxy)], eval_metric='auc', categorical_feature=CATEGORICAL,
            callbacks=[lgb.early_stopping(25, verbose=False)])
    # Separate groups within val for calibration and threshold selection.
    ids = np.sort(val.run_id.unique())
    calibration_mask = val.run_id.isin(ids[::2]).to_numpy()
    raw_val = clf.predict_proba(xv)[:, 1]
    cal = IsotonicRegression(out_of_bounds='clip').fit(raw_val[calibration_mask], val.proxy.to_numpy()[calibration_mask])
    pval = cal.predict(raw_val[~calibration_mask])
    yval = val.proxy.to_numpy()[~calibration_mask]
    precision, recall, thresholds = precision_recall_curve(yval, pval)
    f2 = 5 * precision[:-1] * recall[:-1] / np.maximum(4 * precision[:-1] + recall[:-1], 1e-9)
    eligible = np.where(recall[:-1] >= .7, f2, -1)
    threshold = float(thresholds[int(np.argmax(eligible))])
    pred = reg.predict(xs)
    probs = cal.predict(clf.predict_proba(xs)[:, 1])
    logistic = make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(max_iter=1000, random_state=42))
    logistic.fit(xt, train.proxy)
    logistic_probs = logistic.predict_proba(xs)[:, 1]
    metrics = dict(model_version='pkp-serving-v1', evaluation=label, source='PKP Intercity / real passenger data',
                   trained_at=datetime.now(timezone.utc).isoformat(),
                   rows={'train': len(train), 'val': len(val), 'test': len(test)},
                   runs={'train': int(train.run_id.nunique()), 'val': int(val.run_id.nunique()), 'test': int(test.run_id.nunique())},
                   date_range={'absolute_run_dates': 'not supplied', 'train_months': sorted(train.month.unique().tolist()), 'test_months': sorted(test.month.unique().tolist())},
                   regression=regression(test.delta_delay, pred), classification=classification(test.proxy, probs, threshold),
                   baselines={'zero': regression(test.delta_delay, np.zeros(len(test))),
                              'edge_median': regression(test.delta_delay, xs.edge_delta_delay_P50),
                              'logistic': classification(test.proxy, logistic_probs, .5)},
                   threshold=threshold, proxy_prevalence=float(test.proxy.mean()), features=FEATURES,
                   warning='Прокси ближайшего перегона; перенос на синтетический участок не проверен; грузовые используют правила.',
                   search='Two fixed leaf-count candidates selected by validation MAE; no Optuna.')
    metrics['accepted'] = bool(metrics['regression']['mae'] < min(metrics['baselines'][b]['mae'] for b in ['zero', 'edge_median'])
                               and metrics['classification']['pr_auc'] > metrics['baselines']['logistic']['pr_auc']
                               and metrics['classification']['brier'] < metrics['baselines']['logistic']['brier'])
    metrics['by_category'] = {str(c): regression(test.loc[mask, 'delta_delay'], pred[mask]) for c in test.category_code.unique() if (mask := (test.category_code == c).to_numpy()).sum() > 1}
    metrics['by_delay_bucket'] = {}
    for name, lower, upper in [('0-3', 0, 3), ('3-10', 3, 10), ('10+', 10, float('inf'))]:
        mask = (test.prev_delay_departure_min >= lower) & (test.prev_delay_departure_min < upper)
        if mask.sum() > 1: metrics['by_delay_bucket'][name] = dict(n=int(mask.sum()), **regression(test.loc[mask, 'delta_delay'], pred[mask]))
    metrics['training_seconds'] = time.perf_counter() - started
    out.mkdir(parents=True, exist_ok=True)
    reg.booster_.save_model(str(out / 'reg.txt'))
    clf.booster_.save_model(str(out / 'clf.txt'))
    dump(out / 'features.json', {'features': FEATURES, 'categorical': CATEGORICAL})
    dump(out / 'calibrator.json', {'x': cal.X_thresholds_.tolist(), 'y': cal.y_thresholds_.tolist()})
    edge, station, _ = stats
    profiles = {}
    for name, quantile in [('low', .25), ('median', .5), ('high', .75)]:
        profiles[name] = {col: float(edge[col].quantile(quantile)) for col in edge}
        profiles[name].update({col: float(station[col].quantile(quantile)) for col in station})
    dump(out / 'lookup_edge_stats.json', {'profiles': profiles, 'source': 'train-only quantiles of edge/station statistics'})
    dump(out / 'metrics.json', metrics)
    # LightGBM's exact TreeSHAP implementation avoids an extra SHAP runtime dependency.
    contributions = clf.booster_.predict(xs.iloc[:2000], pred_contrib=True, num_threads=1)[:, :-1]
    importance = np.mean(np.abs(contributions), axis=0)
    dump(out / 'shap_importance.json', dict(zip(FEATURES, importance.tolist())))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reports = SERVICE / 'reports'
    reports.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    order = np.argsort(importance)[-10:]
    ax.barh([FEATURES[i] for i in order], importance[order], color='#246b69')
    ax.set_xlabel('Mean |TreeSHAP|, raw classifier log-odds')
    fig.tight_layout(); fig.savefig(reports / f'{label}_importance.png', dpi=160); plt.close(fig)
    points = metrics['classification']['calibration']
    fig, ax = plt.subplots(figsize=(5, 5)); ax.plot([0, 1], [0, 1], '--', color='grey')
    ax.plot([p['predicted'] for p in points], [p['observed'] for p in points], 'o-')
    ax.set(xlabel='Predicted proxy probability', ylabel='Observed proxy frequency', title=label)
    fig.tight_layout(); fig.savefig(reports / f'{label}_calibration.png', dpi=160); plt.close(fig)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--temporal', action='store_true')
    args = parser.parse_args()
    frame, splits = prepare()
    print('Prepared', frame.shape, 'official split counts', pd.Series(splits).value_counts().to_dict(), flush=True)
    if args.temporal:
        months = sorted(frame.month.unique())
        if len(months) < 3: raise ValueError('At least three months required for month holdout')
        # Whole runs assigned by their first observed month; never random row splitting.
        run_month = frame.groupby('run_id').month.min()
        month = frame.run_id.map(run_month)
        train, val, test = frame[month < months[-2]], frame[month == months[-2]], frame[month == months[-1]]
        label = 'month_holdout'
    else:
        def ids(key):
            if all(isinstance(v, str) for v in splits.values()):
                return [int(k) for k, v in splits.items() if v == key]
            for candidate in [key, key + '_run_ids', 'validation' if key == 'val' else key]:
                if candidate in splits: return splits[candidate]
            raise KeyError(key)
        train, val, test = (frame[frame.run_id.isin(ids(key))] for key in ['train', 'val', 'test'])
        label = 'official'
    for a, b in [(train, val), (train, test), (val, test)]:
        assert not set(a.run_id) & set(b.run_id), 'Run leakage'
    assert min(len(train), len(val), len(test)) > 0
    folder = 'forecast_temporal' if args.temporal else 'forecast_v1'
    metrics = fit(train, val, test, SERVICE / 'models' / folder, label)
    if not args.temporal:
        config_path = SERVICE / 'config/forecast.yaml'
        config = yaml.safe_load(config_path.read_text())
        config['alert_threshold'] = metrics['threshold']
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    print(json.dumps({k: metrics[k] for k in ['accepted', 'regression', 'threshold', 'training_seconds']}), flush=True)


if __name__ == '__main__': main()
