from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    sap_oauth_token_url: str
    sap_oauth_client_id: str
    sap_oauth_client_secret: str
    sap_odata_base: str
    sap_download_base: str

    discover_interval_min: int = 30
    download_concurrency: int = 2

    sar_dir: str = "./storage/sar"
    sapcar_bin: str = "/usr/local/bin/SAPCAR"

    http_timeout_s: float = 60.0
    retry_max_attempts: int = 5


settings = Settings()
