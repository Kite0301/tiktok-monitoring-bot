"""Load configuration from config/accounts.json and environment variables."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    accounts: list[str]
    slack_webhook_url: str
    state_file_path: str = "data/state.json"
    ephemeral_file_path: str = "data/ephemeral.json"
    analytics_delay_hours: int = 24
    max_analytics_retries: int = 3
    max_completed_history: int = 200


def load_config() -> Config:
    """Load accounts from config/accounts.json and secrets from env vars.

    Raises:
        ValueError: If required configuration is missing or invalid.
        FileNotFoundError: If accounts.json does not exist.
    """
    project_root = Path(__file__).resolve().parent.parent
    accounts_path = project_root / "config" / "accounts.json"

    with open(accounts_path, encoding="utf-8") as f:
        data = json.load(f)

    accounts = data.get("accounts", [])
    if not accounts:
        raise ValueError("No accounts configured in config/accounts.json")

    for account in accounts:
        if not account.startswith("@"):
            raise ValueError(
                f"Account '{account}' must start with '@' (e.g. '@username')"
            )

    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not slack_webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL environment variable is not set")

    state_file_path = str(project_root / "data" / "state.json")
    ephemeral_file_path = str(project_root / "data" / "ephemeral.json")

    return Config(
        accounts=accounts,
        slack_webhook_url=slack_webhook_url,
        state_file_path=state_file_path,
        ephemeral_file_path=ephemeral_file_path,
    )
