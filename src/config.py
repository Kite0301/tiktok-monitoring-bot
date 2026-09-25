"""Load configuration from config/accounts.json and environment variables."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Account:
    """One monitored account.

    notify=False collects data silently: no new-post or analytics messages.
    Health alerts (repeated extraction failure, recovery) are still sent, so
    a silent account cannot stop collecting without anyone noticing.
    """

    username: str
    notify: bool = True


@dataclass
class Config:
    accounts: list[Account] = field(default_factory=list)
    slack_webhook_url: str = ""
    data_dir: str = "data/accounts"
    # Pre-split state file. Only read once, to migrate it away.
    legacy_state_file_path: str = "data/state.json"
    analytics_delay_hours: int = 24
    # How late a measurement may be and still count as "24h performance".
    # A post already past this window when first seen gets no analytics job,
    # so that e.g. a 40h-old number never lands in the 24h dataset.
    analytics_max_lateness_hours: int = 6
    max_analytics_retries: int = 3
    # Applies per account, so a prolific account cannot crowd out the others.
    max_completed_history: int = 200
    # Consecutive extraction failures before alerting Slack. Runs land roughly
    # once an hour, so 3 means the account has been failing for a few hours.
    failure_alert_threshold: int = 3

    @property
    def notifying_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.notify]


def _parse_account(entry) -> Account:
    """Accept either "@name" or {"username": "@name", "notify": false}."""
    if isinstance(entry, str):
        return Account(username=entry)
    if isinstance(entry, dict):
        username = entry.get("username")
        if not username:
            raise ValueError(f"Account entry is missing 'username': {entry}")
        return Account(username=username, notify=bool(entry.get("notify", True)))
    raise ValueError(f"Unsupported account entry: {entry!r}")


def load_config() -> Config:
    """Load accounts from config/accounts.json and secrets from env vars.

    Raises:
        ValueError: If required configuration is missing or malformed.
        FileNotFoundError: If config/accounts.json does not exist.
    """
    project_root = Path(__file__).resolve().parent.parent
    accounts_file = project_root / "config" / "accounts.json"

    if not accounts_file.exists():
        raise FileNotFoundError(f"Config file not found: {accounts_file}")

    with open(accounts_file, encoding="utf-8") as f:
        data = json.load(f)

    accounts = [_parse_account(entry) for entry in data.get("accounts", [])]
    if not accounts:
        raise ValueError("No accounts configured in config/accounts.json")

    duplicates = {a.username for a in accounts if
                  [x.username for x in accounts].count(a.username) > 1}
    if duplicates:
        raise ValueError(f"Duplicate accounts configured: {sorted(duplicates)}")

    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not slack_webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL environment variable is not set")

    return Config(
        accounts=accounts,
        slack_webhook_url=slack_webhook_url,
        data_dir=str(project_root / "data" / "accounts"),
        legacy_state_file_path=str(project_root / "data" / "state.json"),
    )
