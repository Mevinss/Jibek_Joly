# Jibek Joly

Көкшетау–Астана–Алматы дәлізінің **синтетикалық** диспетчерлік демосы. Негізгі деректер бір жерде: `data/kz_demo/{KZ,mock,scenarios}`. Олар Қазақстандағы нақты пойыз қозғалысы емес. PKP дерегі тек статистикалық калибрлеуге, DISPLIB тек алгоритм benchmark-іне арналған; екеуі де симулятор пойыздарына қосылмайды.

## Windows-та іске қосу

PowerShell ішінде, репозиторий түбірінен:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\import_kz_demo.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Егер `py` launcher орнатылмаса, бірінші жолда орнатылған `python.exe` толық жолын пайдаланыңыз. Docker қажет емес. Демо деректер репозиторийде `data/kz_demo/` ішінде дайын тұр; аргументсіз importer оларды тексереді және көшірме жасамайды. Нақты ZIP қолжетімді болса: `python scripts\import_kz_demo.py --zip C:\path\to\kz_kokshetau_astana_almaty_data.zip`. Importer ZIP мүшелерінің жолдарын және міндетті файлдарды тексереді. `validation.json` мен деректер README-і сол каталогта сақталады.

Сыртқы екі дерек көзін тікелей жүктеу:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_external_data.py
```

Нәтиже `data/source_manifest.json` ішінде көрсетіледі. PKP ZIP үшін жарияланған MD5 міндетті түрде тексеріледі. DISPLIB толық ZIP алынбаса, ресми екі JSON fallback қолданылады және manifest оған `full_downloaded` деп жазбайды. `data/external/` git-ке кірмейді; `data/kz_demo/` — репозиторийдегі жалғыз негізгі демо дерек орны.

## API

`GET /health`, `GET /metrics`, `GET /api/state`, `POST /api/scenarios/{id}/reset`, `POST /api/scenarios/{id}/start?speed=60`, `POST /api/scenarios/{id}/pause`, `GET /api/history?scenario_id=SCN-ALL&from=...&to=...`, `GET /api/replay?scenario_id=SCN-ALL&at=...`, `POST /api/human-actions`, `WS /ws/state?last_sequence=...`.

Start жылдамдықтары: `1`, `10`, `60` виртуалды секунд / нақты секунд. Reset сценарийді тоқтатады; start қайта жүргізеді. WebSocket әр нақты секундта snapshot немесе heartbeat жібереді; `stale_after_ms=3500`. Қайта қосылған клиент `last_sequence` бойынша 100 оқиғаға дейін алады, одан көп болса толық snapshot алады. [Шағын браузер клиенті](examples/ws_client.html) reconnect пен байланыс үзілуін көрсетеді. History/replay ағымдағы run-ды көрсетеді; бұрынғы run үшін `run_id` жіберуге болады. Replay live күйді өзгертпейді. SQLite соңғы күйді және sequence-ті процесс қайта қосылғанда қалпына келтіреді.

`SCN-01`–`SCN-04` төрт оқиғаны жеке, `SCN-ALL` бірге іске қосады. `SCN-CHAOS` негізгі demo seed-тен бөлек, төрт түрдің әрқайсысынан 10 түрлі оқиға жасайды. Инцидент толық жабылған блоктағы пойызды көшірмейді: ағымдағы блокты аяқтауға рұқсат, жаңа жабық блокқа кіруге тыйым салынады. Қозғалыс логикасы [engine.py](backend/simulator/engine.py) ішінде; optimizer осы `can_enter` ережесін қолдануы керек.

## Тексеру және шектеулер

`python -m unittest discover -s tests -v` бір seed детерминизмін, блоктағы жалғыз occupancy-ді, маршрут прогресін, инциденттердің басталып аяқталуын, Chaos fixture-ді, SQLite restart/replay-ді тексереді. FastAPI мен WebSocket үшін қосымша интеграциялық тексеру `python -m pytest tests/test_api.py` командасында.

Бұл repository-де тапсырма атаған бастапқы `PROJECT_IDEA.md` және `CONTRACTS_AND_METRICS.md` болмады. Екіншісі осы жұмыста нақты интерфейс сипаттамасы ретінде жасалды. Симулятор уақытын 60 секундтан аспайтын қадаммен есептейді; ұсақ қозғалыс пен бекетте тұру уақыты қарапайымдандырылған. Бастапқы кесте синтетикалық, нақты диспетчерлік шешімге арналмаған.


## ML/LLM service and Kazakhstan web demo

The unified dashboard, simulator, planning bridge, and advisory AI service run together on port 8002. Port 8000 remains an optional standalone simulator API:

```powershell
.\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt
.\.venv\Scripts\python.exe -m services.ai.main
```

Open http://127.0.0.1:8002/. The root page uses the persistent, conflict-free 28-train simulator. It offers incident injection, affected trains, FIFO/CP-SAT status, independently simulated decision alternatives, read-only preview, validated apply, ETA, history, and replay on one run. `/legacy` preserves the old frontend, and `/lab.html` preserves the ML laboratory. Local map/SVG and ML work without external internet; OpenAI chat needs internet. The map uses approximate local geometry without a tile server.

The uploaded Kazakhstan archive contains synthetic schedules, not observed delays. `kz-synthetic-schedule-v1` learns scheduled segment duration (test MAE0.566min on SIM services; unseen-segment diagnostic38.245min). It is separate from the PKP delay/proxy model, whose accuracy is unvalidated for Kazakhstan.

See [AI instructions](services/ai/README.md), [full readiness/model audit](services/ai/reports/kz_demo_readiness.md), and `POST /forecast/schedule`, `GET /forecast/schedule-info`, `GET /infra/geometry` in the AI OpenAPI docs. Tests: `python -m pytest services/ai/tests tests -q`.


## Обновлённый диспетчерский экран (RU/KK)

Запустите AI-сервис командой выше и откройте http://127.0.0.1:8002/.
В шапке: РУС / ҚАЗ, светлая / тёмная тема, сценарий, пауза и ×1 / ×10 / ×60.
Настройки языка и темы сохраняются локально. Английский и отдельный режим машиниста не включены.
Светлая тема начальная, все шрифты, i18next и MapLibre загружаются из репозитория.
Node-сборка не нужна. При отсутствии WebGL карта автоматически переходит на SVG-схему.

«Лаборатория ML» содержит тестовые MAE, калибровку отдельной метки роста задержки ≥3 мин,
SHAP старого прокси-классификатора и реальный тестовый пробег PKP.
`POST /forecast/advisory` добавляет известное ожидание, OOD, интервал и опциональный буфер солверу;
старый `/forecast` сохранён для совместимости. Числа PKP не выдаются за проверенный прогноз Казахстана.

A/B/C в основном сценарии — независимые прогнозы из одного snapshot на 20 виртуальных минут. Выбор «Предпросмотр» не меняет текущий запуск; «Применить» записывает проверенную задержку поезда в SQLite и меняет симулятор. FIFO и CP-SAT вызываются на том же snapshot, но не применяются, пока занятость станционных путей проверена не полностью. Показатель качества — обозначенная демо-эвристика снимка; профиль скорости показывает пределы линии и поезда, без физического расчёта энергии. Отдельные сценарии `SCN-ALL` (timetable playback) и `SCN-SHORT` (3-поездная проверка) не смешиваются с главным запуском.
Казахские переводы требуют проверки носителем (`TODO-review-kk`). В KK чат сейчас даёт локальную сводку;
LLM-чат доступен в RU, ключ хранится только в серверном `.env`.

Аудит и ограничения: [модель](docs/MODEL_AUDIT.md), [интеграция солвера](docs/SOLVER_CONTRACT.md),
[проверка редизайна](docs/design/VALIDATION.md). Скриншоты находятся в `docs/design/`.
