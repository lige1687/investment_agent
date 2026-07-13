"""Application configuration via pydantic-settings."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///data/financial.db"

    # Security
    secret_key: str = "dev-secret-change-in-production"
    access_token_expire_minutes: int = 1440

    # ── LLM: default (used when a per-role provider is not set) ──
    # provider: "anthropic" | "deepseek" | "qwen" | "moonshot" | "kimi" | "zhipu" | "openai"
    # Empty strings for model/key/base_url so legacy `anthropic_*` fields
    # can seed the values via the fallback path in llm/registry.py.
    llm_provider: str = "anthropic"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 60.0

    # ── LLM: per-role overrides ──
    # Each role can pick its own provider/model/key. Empty string = fall back to
    # the default llm_* values above. Roles used by the agent layer:
    #   - intent_router: cheap classification, slot filling
    #   - advisor:       decision-copilot chat (main investment Q&A)
    #   - scout:         opportunity scanning
    #   - guardian:      holding health monitor
    llm_intent_router_provider: str = ""
    llm_intent_router_model: str = ""
    llm_intent_router_api_key: str = ""
    llm_intent_router_base_url: str = ""

    llm_advisor_provider: str = ""
    llm_advisor_model: str = ""
    llm_advisor_api_key: str = ""
    llm_advisor_base_url: str = ""

    llm_scout_provider: str = ""
    llm_scout_model: str = ""
    llm_scout_api_key: str = ""
    llm_scout_base_url: str = ""

    llm_guardian_provider: str = ""
    llm_guardian_model: str = ""
    llm_guardian_api_key: str = ""
    llm_guardian_base_url: str = ""

    # ── Legacy Anthropic fields (still read by other code paths) ──
    # New code should route through llm_* + the registry.
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    ths_api_base_url: str = "https://api.10jqka.com.cn"

    # Feishu
    feishu_webhook_url: str = ""
    # Guardian scheduling & push
    guardian_push_enabled: bool = True
    guardian_scheduler_enabled: bool = True

    # Yangjibao — browser-plug-api (same as FundVal-Live)
    yangjibao_api_base_url: str = "http://browser-plug-api.yangjibao.com"
    yangjibao_api_secret: str = ""  # YJB_API_SECRET, shared with FundVal-Live

    # Application
    debug: bool = True
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"

    @property
    def db_path(self) -> Path:
        """Extract file path from sqlite URL."""
        # "sqlite+aiosqlite:///data/financial.db" → Path("data/financial.db")
        db_part = self.database_url.replace("sqlite+aiosqlite:///", "")
        return Path(db_part)


settings = Settings()
