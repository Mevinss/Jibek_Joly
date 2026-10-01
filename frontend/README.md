# Jibek Joly frontend

`index.html` is the single entry point for the dispatcher site. Start the AI service from the repository root with `python -m services.ai.main`, then open `http://127.0.0.1:8002/` or `http://127.0.0.1:8002/frontend/`.

The page uses the existing panels, visual tokens, RU/KK locales, and JavaScript from `services/ai/web`. The FastAPI service supplies its assets and API endpoints. New dashboard and statistics panels should extend this page and its shared code, using actual data with clearly labelled demo boundaries.
