from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    wg_interface: str = "wg0"
    wg_port: int = 51820
    wg_network: str = "10.10.0.0/24"
    wg_endpoint: str = ""
    wg_dns: str = "1.1.1.1,8.8.8.8"

    database_url: str = "sqlite+aiosqlite:///./wg_agent.db"
    api_key: str = "change-me"

    stats_interval: int = 10

    class Config:
        env_file = ".env"
        env_prefix = ""


settings = Settings()
