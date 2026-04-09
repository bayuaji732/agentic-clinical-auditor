from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = "gpt-4o"

    extraction_confidence_threshold: float = 0.95
    critical_recall_floor: float = 1.0
    precision_target: float = 0.99

    kb_version: str = "v2026.04.01-LTS"
    rxnorm_db_path: str = "kb/rxnorm.db"
    snomed_db_path: str = "kb/snomed.db"
    ddi_rules_path: str = "kb/ddi_rules.json"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
