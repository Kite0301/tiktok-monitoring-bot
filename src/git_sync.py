"""Commit and push data/state.json back to the repository.

Only meaningful when running inside GitHub Actions, where the checkout has
push access via the workflow's `contents: write` permission.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

STATE_FILE = "data/state.json"

# Attribution for commits made by the workflow.
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def commit_and_push(message: str) -> None:
    """Stage the state file, commit it and push to origin.

    Does nothing if the file has no staged changes. Raises
    subprocess.CalledProcessError if any git command fails.
    """
    subprocess.run(["git", "config", "user.name", BOT_NAME], check=True)
    subprocess.run(["git", "config", "user.email", BOT_EMAIL], check=True)
    subprocess.run(["git", "add", STATE_FILE], check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], capture_output=True
    )
    if result.returncode == 0:
        logger.info("No staged changes; skipping commit")
        return

    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)
