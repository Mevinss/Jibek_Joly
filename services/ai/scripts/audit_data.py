from pathlib import Path
import json
import os
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / 'services/ai/reports'


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = ['# Аудит данных', '', '## Hugging Face файл', '']
    path = Path(os.environ.get('HF_DATA_PATH', ROOT / 'data/hf/data-2025-07.parquet'))
    if path.exists():
        frame = pd.read_parquet(path)
        info = {'bytes': path.stat().st_size, 'rows': len(frame), 'columns': {c: str(t) for c, t in frame.dtypes.items()},
                'missing': frame.isna().sum().to_dict(), 'duplicate_rows': int(frame.duplicated().sum()),
                'duplicate_ids': int(frame['id'].duplicated().sum()) if 'id' in frame else None}
        for col in ['time', 'arrival_planned_time']:
            if col in frame: info[col] = {'min': str(frame[col].min()), 'max': str(frame[col].max())}
        if 'delay_in_min' in frame:
            info['delay_quantiles'] = frame.delay_in_min.quantile([0, .5, .9, .99, 1]).to_dict()
        if 'train_type' in frame: info['train_types'] = frame.train_type.value_counts().to_dict()
        (REPORTS / 'hf_audit.json').write_text(json.dumps(info, ensure_ascii=False, indent=2, default=int), encoding='utf-8')
        report += [f"Размер: {info['bytes']} байт, {len(frame):,} строк, {len(frame.columns)} колонок.",
                   'Схема, пропуски, дубли, категории и распределения сохранены в hf_audit.json.',
                   'Это записи движения поездов: названия немецких станций, типы RE/S/ICE и др., задержки и времена.',
                   'Название файла не подтверждает происхождение и лицензию. URL исходного репозитория не предоставлен.',
                   'Соответствие: train_type → type; delay_in_min × 60 → delay_s; time → ts; eva → станция, НЕ блок.',
                   'Нет совместимого segment_id PKP, резервов расписания, исторических профилей и прямого delta_delay.',
                   '**Решение: исключить из обучения и численной внешней валидации v1.** Без общей задачи и признаков метрики несопоставимы.',
                   'Возможен отдельный будущий benchmark после подтверждения лицензии, восстановления рейсов и предыдущих отправлений.',
                   'Утечки: arrival_change_time, departure_change_time и delay_in_min относятся к наблюдаемому исходу; нельзя использовать их для предсказания того же исхода.', '']
        del frame
    else:
        report += ['Файл отсутствует. Исключён; метрики не вычислялись.', '']
    report += ['## PKP Intercity', '']
    files = list((ROOT / 'data/pkp').rglob('train_delays_tabular.parquet'))
    if files:
        path = files[0]
        f = pd.read_parquet(path)
        info = {'rows': len(f), 'columns': {c: str(t) for c, t in f.dtypes.items()},
                'missing': f.isna().sum().to_dict(), 'duplicate_rows': int(f.duplicated().sum()),
                'duplicate_run_stop': int(f.duplicated(['run_id', 'stop_order']).sum()),
                'target_quantiles': f.delta_delay.quantile([0, .01, .5, .9, .99, 1]).to_dict(),
                'proxy_rate': float(((f.delta_delay >= 3) | f.difficulty_id.isin([5, 6, 7, 34, 36, 39])).mean()),
                'categories': f.category_code.value_counts().to_dict()}
        (REPORTS / 'pkp_audit.json').write_text(json.dumps(info, indent=2, default=int), encoding='utf-8')
        report += [f"Проверенный архив: MD5 7628d3022ec6f257864492ef9d1b3262. Таблица: {len(f):,} строк, {len(f.columns)} колонок.",
                   f"Прокси-класс delta_delay ≥ 3 или difficulty_id ∈ {{5,6,7,34,36,39}}: {info['proxy_rate']:.3%}.",
                   'Полная схема и статистика: pkp_audit.json. В raw/run_stops.csv есть только время суток, без даты рейса; train_runs.csv в архиве отсутствует.',
                   'Точные даты рейсов и hold-out последних двух недель восстановить достоверно нельзя. Вместо него предусмотрен отдельный hold-out по месяцам из month_sin/cos.',
                   'Загрузка перегона ±30 минут между рейсами не вычисляется: без дат смешались бы разные дни. block_load исключён из признаков модели v1.',
                   'Удаляются 284 полных дубликата таблицы до сплитов и соединения с остановками.',
                   'difficulty_id используется только для метки, run_id/stop_order только для объединений и разбиения.',
                   'Строки с восстановленной prev_delay_departure_min исключаются: исходное восстановление использовало будущие прибытия.',
                   'Исторические статистики пересчитываются на обучающих рейсах с OOF-разбиением по run_id; test/val не участвуют.',
                   'Готовые rolling-статистики, минимальное время хода и активные события имеют ограничения происхождения; см. model_report.md.',
                   'Грузовых нет. Прокси не является разметкой реальных конфликтов или строго пятнадцатиминутного горизонта.', '']
    else:
        report += ['Архив ещё не получен или не проверен. Обучение и метрики PKP пока недоступны.', '']
    report += ['## Источники', '',
               'Marek Kostrz, PKP Intercity delays, Zenodo, https://doi.org/10.5281/zenodo.21700869. CC BY 4.0.',
               'Страница источника указывает некоммерческое академическое/учебное использование; атрибуция сохранена.',
               'DISPLIB 2025 — внешний benchmark солвера участника 2, в обучение ML не входит.']
    (REPORTS / 'data_audit.md').write_text('\n\n'.join(report), encoding='utf-8')
    print('Audit saved:', REPORTS)


if __name__ == '__main__': main()
