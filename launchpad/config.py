import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Reward:
    referrals: int
    label: str


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    use_ssl: bool


@dataclass(frozen=True)
class Config:
    product_name: str = "Your Product"
    tagline: str = "One line that says why people should care."
    description: str = ""
    benefits: tuple[str, ...] = ()
    rewards: tuple[Reward, ...] = ()
    base_url: str = "http://localhost:8000"
    from_name: str = ""
    from_email: str = "hello@example.com"
    postal_address: str = ""
    db_path: str = "launchpad.db"
    host: str = "127.0.0.1"
    port: int = 8000
    trust_proxy: bool = False
    send_delay_seconds: float = 1.0
    smtp: SmtpSettings | None = None


def load_config(path=None) -> Config:
    raw: dict = {}
    if path is not None:
        with Path(path).open("rb") as handle:
            raw = tomllib.load(handle)

    rewards = tuple(
        Reward(int(item["referrals"]), str(item["label"]))
        for item in raw.pop("rewards", [])
    )
    rewards = tuple(sorted(rewards, key=lambda reward: reward.referrals))
    benefits = tuple(str(item) for item in raw.pop("benefits", []))
    base_url = str(raw.pop("base_url", Config.base_url)).rstrip("/")

    try:
        config = Config(benefits=benefits, rewards=rewards, base_url=base_url, **raw)
    except TypeError as error:
        raise ValueError(f"unknown config key: {error}") from None
    return _with_smtp_from_env(config)


def _with_smtp_from_env(config: Config) -> Config:
    host = os.environ.get("LAUNCHPAD_SMTP_HOST", "")
    if not host:
        return config
    use_ssl = os.environ.get("LAUNCHPAD_SMTP_SSL", "").lower() in ("1", "true")
    smtp = SmtpSettings(
        host=host,
        port=int(os.environ.get("LAUNCHPAD_SMTP_PORT", "465" if use_ssl else "587")),
        user=os.environ.get("LAUNCHPAD_SMTP_USER", ""),
        password=os.environ.get("LAUNCHPAD_SMTP_PASSWORD", ""),
        use_ssl=use_ssl,
    )
    return Config(**{**config.__dict__, "smtp": smtp})
