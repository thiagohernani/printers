import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env():
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

SELBETTI_USER = os.environ["SELBETTI_USER"]
SELBETTI_PASS = os.environ["SELBETTI_PASS"]
SIMPRESS_USER = os.environ["SIMPRESS_USER"]
SIMPRESS_PASS = os.environ["SIMPRESS_PASS"]
JIRA_URL = os.environ["JIRA_URL"]
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
