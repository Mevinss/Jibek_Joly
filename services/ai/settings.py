from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SERVICE = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    ai_port: int = 8002
    use_fixtures: bool = True
    llm_provider: str = 'openai'
    llm_api_key: SecretStr = SecretStr('')
    llm_model_chat: str = 'gpt-4.1-mini'
    llm_model_fast: str = 'gpt-4.1-mini'
    platform_url: str = 'http://127.0.0.1:8000'
    solver_url: str = 'http://127.0.0.1:8001'
    hf_data_path: str = 'data/hf/data-2025-07.parquet'
    requests_per_minute: int = 20


settings = Settings()
