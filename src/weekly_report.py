"""Weekly Slack report entry point.

Sends a weekly operational status summary to Slack, including
a description of the bot's features and the list of monitored accounts.

Exit codes:
    0 = Success
    1 = Unrecoverable error
"""

import logging
import sys
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from slack_notifier import SlackNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Send the weekly report to Slack."""
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {e}")
        return 1

    notifier = SlackNotifier(config.slack_webhook_url)

    try:
        notifier.notify_weekly_report(config.accounts)
        logger.info("Weekly report sent successfully")
    except Exception as e:
        logger.error(f"Failed to send weekly report: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
