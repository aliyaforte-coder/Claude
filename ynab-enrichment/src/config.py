from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # YNAB
    ynab_api_token: str = ""
    ynab_budget_id: str = "last-used"
    ynab_base_url: str = "https://api.ynab.com/v1"
    ynab_rate_limit: int = 200  # requests per hour

    # SimpleFin
    simplefin_setup_token: str = ""
    simplefin_access_url: str = ""

    # Amazon
    amazon_export_path: str = "./data/amazon_order_history.csv"

    # API security
    api_key: str = ""

    # Database
    database_url: str = "sqlite:///./data/ynab_enrichment.db"

    # Matching tolerances
    date_tolerance_days: int = 2
    amazon_date_tolerance_days: int = 3
    confidence_threshold: float = 0.8

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def get_db_path() -> str:
    """Extract the file path from the SQLite URL."""
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return "data/ynab_enrichment.db"


def get_category_mappings_path() -> Path:
    return Path("data/category_mappings.json")
