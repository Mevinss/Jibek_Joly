# Контракт будущего солвера

Рабочего CP-SAT в репозитории нет. Fixture ответы не считаются результатом оптимизации. UI сравнения показывает «Не подключён». Расчёт Человек/FIFO — отдельная учебная задача двух поездов у одного ресурса, не план для 28 поездов карты.

Вход адаптера: snapshot_id, seed, trains[{train_id, block_id, earliest_entry_s, technical_duration_s, priority, duration_buffer_s}], closures[{block_id, start_s, end_s}], capacity.

`duration_buffer_s` берётся из `/forecast/advisory.solver_buffer_s` только при reliable=true. k читается из `services/ai/config/advisory.yaml`. null означает непроверенную оценку; это НЕ нулевой запас. Платформа должна выбрать свою консервативную политику.

Выход: snapshot_id, seed, status (optimal/feasible/infeasible/unavailable), plan[{train_id,block_id,entry_s,exit_s}], objective, measured_compute_ms, total_delay_min, conflicts, energy_proxy и energy_proxy_formula. Сравнивать FIFO/CP-SAT/CP-SAT+ML можно только при одинаковых исходном снимке, seed, горизонте, ограничениях и формуле энергии. Ошибки/timeout не подменяются фикстурами.

Учебная локальная задача: один ресурс, no-overlap, 2 мин разделение, готовность/длительность детерминированы seed. A/B меняют порядок; C добавляет 5 мин ожидания после открытия и удваивает длительность прохода (условно 30 вместо 60 км/ч). Энергия-прокси = сумма duration*(relative_speed)^2; не кВт·ч. Δ учебного индекса = разность max(0,100−sum_wait/2) с FIFO; это не индекс всей карты. Таймер 20 с настенных часов, default C записывается в журнал.
