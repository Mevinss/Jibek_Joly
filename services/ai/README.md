# TurkiSib — Автодиспетчер

Сервис участника №3: ML-прогноз задержки и прокси-риска, OpenAI-агент «Старший диспетчер», телеграммы и рапорт. Работает автономно на явно помеченных фикстурах платформы/солвера.

**Демонстрационная консультативная система. Не заменяет сертифицированные системы безопасности движения и СЦБ.**

## Запуск

Python 3.11, без Docker. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
Copy-Item .env.example .env  # только если .env ещё нет
# Внесите LLM_API_KEY локально; не публикуйте ключ.
.\run_ai.ps1
```

macOS: `python3.11 -m venv .venv`, `.venv/bin/python -m pip install -r services/ai/requirements.txt`, `cp .env.example .env`, `sh run_ai.sh`. Для LightGBM на macOS может потребоваться OpenMP (`brew install libomp`).

Swagger: http://127.0.0.1:8002/docs. Проверка: http://127.0.0.1:8002/health. В VS Code есть конфигурация **AI service :8002**; для F5 нужен Python Debugger extension. Из терминала VS Code доступен тот же run_ai.ps1.

## Интерактивный экран

Откройте **http://127.0.0.1:8002/** после запуска сервиса. UI работает на HTML/CSS/JavaScript рядом с FastAPI; установка Node.js не требуется. Шрифт Golos Text включён локально под OFL.

Главный экран показывает казахстанский маршрут Көкшетау — Астана — Алматы: 28 SIM-поездов, карту с автономным SVG-режимом, поездограмму и условную схему станции. Выбор поезда синхронизирует карту, прогноз, схему и чат. Доступны пауза, темп ×10, события, просмотр записанной истории и CSV.

1. Выберите поезд на карте, поездограмме или в списке.
2. Измените опоздание и резерв в панели модели: прогноз использует настоящий `/forecast`.
3. Учебная KZ-модель отдельно оценивает время всего перегона по синтетическому расписанию; это не прогноз задержки.
4. Нажмите «Объясни прогноз выбранного поезда»: агент получает текущий снимок. При недоступности API доступна шаблонная сводка.

Исходная лаборатория модели сохранена по `/lab.html`. Главная карта использует собственное демонстрационное воспроизведение расписания; подключение к платформе и солверу ещё предстоит. Планы CP-SAT, индекс качества и выигрыш у FIFO здесь не рассчитываются. Ключ остаётся в серверном `.env`.

KZ-модель обучена на 128 примерах. MAE на 32 тестовых строках — 0.566 мин; на полностью новом перегоне — 38.245 мин. Это качество воспроизведения синтетического расписания, не точность на реальных поездках ҚТЖ. [Полный аудит и ограничения](reports/kz_demo_readiness.md).

Повторное обучение из данных репозитория (команды выполняются из корня):

```powershell
.\.venv\Scripts\python.exe -m services.ai.training.train_kz_schedule --data-dir data/kz_demo/KZ
```

Второй терминал — воспроизводимый показ:

```powershell
.\.venv\Scripts\python.exe -m services.ai.scripts.demo
```

Демо прогнозирует 25 поездов, затем задаёт агенту вопрос о закрытии Б–В на 20 минут. Чат показывает вызов `run_whatif` и значения ответа. В режиме фикстур это заранее подготовленный пример интеграции, **не измеренная победа оптимизатора над FIFO**. Полноценный симулятор/CP-SAT/UI выполняют участники 1, 2, 4.

## Проверено

Модель A LightGBM обучена на 530 887 строках после удаления дубликатов и восстановленных предыдущих задержек. Использован официальный split по рейсам. MAE изменения задержки на test: **0.586 минуты**, baseline delta=0: **0.653**, baseline медианы перегона: **0.647**. ROC-AUC прокси-класса: **0.880**, PR-AUC **0.266**. При пороге, выбранном на val: recall **0.756**, precision **0.198** — ложных предупреждений много, это ограничение обязательно озвучивать.

Отдельная проверка март → апрель → май: MAE **0.823**, ROC-AUC **0.838**. Это hold-out месяца, не последних двух недель: календарные даты рейсов отсутствуют в опубликованном архиве.

25 поездов, 100 прогонов после прогрева: HTTP TestClient p95 **6.80 мс**, вычисления **4.23 мс** на этой машине. Это локальный замер, не сетевой SLA. Подробности и воспроизводимый benchmark — `services/ai/reports/latency.json`.

```powershell
.\.venv\Scripts\python.exe -m pytest services/ai/tests -q
.\.venv\Scripts\python.exe -m services.ai.eval.run_agent_eval
.\.venv\Scripts\python.exe -m services.ai.eval.run_agent_eval --live
.\.venv\Scripts\python.exe -m services.ai.scripts.benchmark
```

`--live` использует платный OpenAI API. Отчёт отдельно считает ответы LLM и резервные ответы: успешный fallback не означает успешный вызов LLM.

## Данные и обучение

Текущая версия `pkp-main-298694c` переобучена из проверенного снимка `main` (коммит `298694c0dccc564bc686560a9e98bbaae3c76900`). PKP в нём совпал с прежним набором после нормализации переносов строк Git; новых реальных обучающих примеров нет. Результаты воспроизвелись без улучшения или ухудшения. [Отчёт переобучения](reports/main_retraining.md) объясняет, почему DISPLIB и синтетическое расписание KZ не являются дополнительными размеченными примерами.

```powershell
.\.venv\Scripts\python.exe -m services.ai.scripts.sync_main_data --ref 298694c0dccc564bc686560a9e98bbaae3c76900
.\.venv\Scripts\python.exe -m services.ai.training.train --data-dir data/main-source/data/external/pkp/pkp_intercity_delays_dataset --output-dir services/ai/models/forecast_main --model-version pkp-main-298694c --source-commit 298694c0dccc564bc686560a9e98bbaae3c76900
```

Для новой итерации выбирайте отдельный `--output-dir`, проверьте метрики и только после этого меняйте `model_directory` в `services/ai/config/forecast.yaml`. Предыдущие артефакты `forecast_v1` сохранены для сравнения/отката. `--output-dir` не меняет порог работающей модели; инференс использует порог из загруженного артефакта. `sync_main_data --ref main` фиксирует текущий SHA, проверяет Git blob SHA каждого файла и сохраняет документы/данные в gitignored `data/main-source`.

```powershell
.\.venv\Scripts\python.exe services/ai/scripts/download_data.py
.\.venv\Scripts\python.exe services/ai/scripts/audit_data.py
.\.venv\Scripts\python.exe -m services.ai.training.train
.\.venv\Scripts\python.exe -m services.ai.training.train --temporal
```

PKP: [Marek Kostrz, PKP Intercity delays, Zenodo](https://doi.org/10.5281/zenodo.21700869), CC BY 4.0; источник указывает учебное/некоммерческое академическое использование. Архив 64 492 235 байт, MD5 `7628d3022ec6f257864492ef9d1b3262`. Скрипт поддерживает повторную загрузку частями и проверяет MD5 перед распаковкой. Сырые данные в `data/` не коммитятся. Малые текстовые модели и отчёты включены.

HF `data-2025-07.parquet`: 2 051 978 строк; файл скопирован локально в `data/hf`. Исключён из обучения и внешней валидации из-за несовместимой задачи и неизвестного происхождения/лицензии. См. `services/ai/reports/data_audit.md`.

DISPLIB 2025 — внешний benchmark солвера участника 2; для ML не используется.

## Ограничения и следующий этап

- Обучение на реальных пассажирских данных PKP; применение к синтетическому участку не валидировано. Грузовые и неизвестные типы обслуживаются правилами.
- `p_conflict_15m` — имя контракта для прокси ближайшего перегона, не достоверная вероятность конфликта за 15 минут. `horizon_min=null` делает это явным.
- `difficulty_id` — только метка. Статистики пересчитаны с исключением test/val; обучающие значения получены по группам без собственного рейса.
- Без дат PKP нельзя вычислить загрузку ±30 минут или двухнедельный hold-out. block_load не включён в модель. Потребуется таблица `run_id → service_date`.
- Модель B на всех 57 колонках не построена: среди них есть таргет, постфактум-метка и идентификаторы. Для корректного расширенного benchmark нужен отдельный отбор признаков. P90-регрессия и Optuna пока не добавлены.
- Числовой grounding не доказывает корректность смысловой привязки цифры. Текст проверяется до SSE-отправки; при ошибке возвращается шаблон.
- Телеграммы и рапорты в текущей версии шаблонные. Сервис ничего не отправляет в Telegram и не изменяет движение.
- Реальные API платформы и солвера пока не предоставлены. Их пути и предлагаемые контракты описаны в `services/ai/docs/integration.md`; текущие фикстуры не заменяют интеграционный прогон.

Для сильного общего демо нужны один snapshot и seed, валидные FIFO/CP-SAT планы, измеренная разница задержки, UI с явным происхождением данных и затем объяснение результата агентом. Заранее заданные цифры фикстур не использовать как итоговые метрики на защите.


## Kazakhstan map and uploaded-archive model

Open `http://127.0.0.1:8002/` for Kazakhstan-only map, 28 SIM trains, SSE playback, linked diagram, station scheme and snapshot chat. The previous parameter laboratory is `/lab.html`. MapLibre and country/route geometry are local; optional OSM background requires internet. `/infra/geometry` returns the56synthetic fixture blocks.

The uploaded KZ archive contains only scheduled times. `kz-synthetic-schedule-v1` therefore learns **synthetic scheduled segment duration**, not actual delay. It is served separately at `POST /forecast/schedule`; metadata at `/forecast/schedule-info`. Reproduce with `python -m services.ai.training.train_kz_schedule --data-dir data/kz-upload/data/KZ`. The PKP delay model remains separate; its accuracy is not validated for Kazakhstan.

See [full training, readiness and credit audit](reports/kz_demo_readiness.md). Train movement is timetable playback, not a conflict-free optimizer. ATO, solver alternatives and quality-index integration remain team work.
