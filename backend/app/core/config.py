from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # App
    APP_ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Mapbox
    MAPBOX_SECRET_TOKEN: str = ""

    # Kroger Developer API (developer.kroger.com — free)
    KROGER_CLIENT_ID: str = ""
    KROGER_CLIENT_SECRET: str = ""

    # Target Redsky API public web-app key
    TARGET_API_KEY: str = ""

    # AI — Groq API key for semantic deal matching
    GROQ_API_KEY: str = ""

    # RAG / local AI
    OLLAMA_HOST: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    RAG_TOP_K: int = 8
    RAG_MAX_TURNS: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
