import os

HYPERSCALERS = {
    "MSFT":  "0000789019",
    "GOOGL": "0001652044",
    "META":  "0001326801",
    "AMZN":  "0001018724",
    "ORCL":  "0001341439",
    "NVDA":  "0001045810",
}

NEOCLOUDS = {
    "CRWV": "0001769628",
    "APLD": "0001144879",
    "IREN": "0001878848",
    "NBIS": "0001513845",
}


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"required environment variable {name} is not set")
    return v


def sec_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "catalyst-tracker cyprien0312@gmail.com")
