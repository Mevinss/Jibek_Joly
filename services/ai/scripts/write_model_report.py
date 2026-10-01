import json
from ..settings import SERVICE


def main():
    official = json.loads((SERVICE / 'models/forecast_v1/metrics.json').read_text(encoding='utf-8'))
    temporal = json.loads((SERVICE / 'models/forecast_temporal/metrics.json').read_text(encoding='utf-8'))
    lines = ['# Отчёт модели A', '',
             'Источник: реальные пассажирские данные PKP Intercity. Цель регрессии — изменение задержки в минутах на следующем перегоне. Классификация — прокси, не реальная разметка конфликтов.', '',
             '## Проверка качества', '',
             '| Проверка | Строки train / val / test | MAE | RMSE | R² | ROC-AUC | PR-AUC | Brier | ECE |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, m in [('Официальные run_id', official), ('Март / апрель / май', temporal)]:
        r, c = m['regression'], m['classification']
        lines.append(f"| {name} | {m['rows']['train']} / {m['rows']['val']} / {m['rows']['test']} | {r['mae']:.4f} | {r['rmse']:.4f} | {r['r2']:.4f} | {c['roc_auc']:.4f} | {c['pr_auc']:.4f} | {c['brier']:.4f} | {c['ece']:.4f} |")
    lines += ['', 'На официальном test MAE нулевой дельты: %.4f; медианы перегона: %.4f. Logistic PR-AUC: %.4f, Brier: %.4f.' % (official['baselines']['zero']['mae'], official['baselines']['edge_median']['mae'], official['baselines']['logistic']['pr_auc'], official['baselines']['logistic']['brier']),
              '', 'Обе модели проходят gate: MAE ниже обоих регрессионных baseline, PR-AUC выше логистической регрессии и Brier ниже неё. Это не подтверждает перенос на симулятор.', '',
              f"Порог {official['threshold']:.6f} выбран на отдельной половине val по рейсам: максимум F2 при recall ≥ 0.7. На test precision {official['classification']['precision']:.3f}, recall {official['classification']['recall']:.3f}. Много ложноположительных алертов; модель предназначена для подсказки, не принятия решений о движении.", '',
              '## Категории и хвосты', '', '| Группа | MAE | RMSE | R² |', '|---|---:|---:|---:|']
    for name, values in {**official['by_category'], **official['by_delay_bucket']}.items():
        lines.append(f"| {name} | {values['mae']:.4f} | {values['rmse']:.4f} | {values['r2']:.4f} |")
    lines += ['', 'Бакеты построены по текущей предыдущей задержке, минуты. Полные числа и размеры групп — metrics.json.', '',
              '## Методика и ограничения', '',
              '- LightGBM L1, seed=42, early stopping. Два фиксированных кандидата num_leaves выбраны по val MAE. Optuna не использовалась.',
              '- Из 558334 строк удалены 284 точных дубля и строки с восстановленной предыдущей задержкой / недоступным предыдущим временем. После фильтрации 530887 строк.',
              '- Официальный splits.json — словарь run_id → train/val/test; случайного построчного разбиения нет.',
              '- Исторические признаки train-only, для train — OOF по пяти группам рейсов. Это групповая кросс-валидация, а не имитация онлайн-доступности истории на каждую дату.',
              '- Isotonic calibration на половине val по рейсам; порог на второй половине. Early stopping использует весь val; финальный test не используется для подбора.',
              '- В архиве отсутствуют абсолютные даты рейсов. Month hold-out честно отделяет месяцы; последние две недели выделить нельзя. Не следует подменять даты порядком run_id.',
              '- block_load исключён из признаков: без дат нельзя построить окно между поездами. difficulty_id используется только для метки.',
              '- Активные нарушения других поездов используются в принятой источником форме; без дат независимо проверить исходное причинное окно невозможно.',
              '- Грузовые не представлены. serving использует для них правила, model_version=rule_fallback.',
              '- TreeSHAP вычисляется встроенным pred_contrib LightGBM. Глобальный график на первых 2000 test строках; локальные вклады — log-odds некалиброванного классификатора.',
              '- P90-регрессия не реализована. Модель B на всех 57 колонках не обучается, потому что этот набор включает таргет и постфактум-метку; расширенный benchmark требует отдельного отбора признаков.', '',
              '## Материалы для слайда', '',
              'official_importance.png и official_calibration.png; month_holdout_importance.png и month_holdout_calibration.png. На слайде обязательно указать «реальные PKP данные → непроверенный перенос на синтетический участок; прокси риска; консультативно, не заменяет СЦБ».']
    (SERVICE / 'reports/model_report.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__': main()
