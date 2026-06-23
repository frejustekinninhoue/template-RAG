from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API keys
    JWT_SECRET: str = "change-me-in-prod"
    GOOGLE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_TRACING_V2: str = "true"
    PAGEINDEX_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # Service URLs
    GPTCACHE_URL: str = "http://gptcache:8001"
    RIVAL_URL: str = "http://rival-service:8002"
    MONGODB_URI: str = "mongodb://mongodb:27017"
    POSTGRES_DSN: str = "postgresql://postgres:postgres@postgres:5432/support_bot"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    OPENAI_BASE_URL: str = ""

    # Tuning
    MAX_INPUT_CHARS: int = 4000
    MAX_SESSION_TURNS: int = 10
    FAITHFULNESS_THRESHOLD: float = 0.7
    COMPLETENESS_THRESHOLD: float = 0.6

    # Model selection (provider can be: gemini | openai | groq | openai_compatible)
    LOW_COMPLEXITY_PROVIDER: str = "gemini"
    LOW_COMPLEXITY_MODEL: str = "gemini-2.0-flash"
    HIGH_COMPLEXITY_PROVIDER: str = "gemini"
    HIGH_COMPLEXITY_MODEL: str = "gemini-2.5-pro"

    # Query intelligence (router). Leave empty to reuse low complexity settings.
    QUERY_INTELLIGENCE_PROVIDER: str = ""
    QUERY_INTELLIGENCE_MODEL: str = ""

    # Tree search model for retrieval stage
    TREE_SEARCH_PROVIDER: str = "gemini"
    TREE_SEARCH_MODEL: str = "gemini-2.0-flash"

    # Completeness judge model
    COMPLETENESS_JUDGE_PROVIDER: str = "gemini"
    COMPLETENESS_JUDGE_MODEL: str = "gemini-2.0-flash"

    # Ragas faithfulness judge (currently OpenAI-backed)
    FAITHFULNESS_EVAL_ENABLED: bool = True
    FAITHFULNESS_JUDGE_MODEL: str = "gpt-4o-mini"

    # Retrieval across multiple indexed docs
    RETRIEVAL_DOC_IDS: str = ""   # comma-separated doc_ids
    RETRIEVAL_DOMAINS: str = ""   # comma-separated metadata domains
    RETRIEVAL_MAX_DOCS: int = 20

    # Google Drive incremental ingestion
    DRIVE_FOLDER_ID: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "./secrets/google-service-account.json"
    DRIVE_SYNC_STATE_COLLECTION: str = "sync_state"

    class Config:
        env_file = ".env"


settings = Settings()
