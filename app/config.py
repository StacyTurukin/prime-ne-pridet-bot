from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_user_id: int
    database_path: str
    default_timezone: str

def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN is missing in .env")

    try:
        admin_id = int(os.getenv("ADMIN_USER_ID", "0").strip() or "0")
    except ValueError:
        admin_id = 0

    return Config(
        bot_token=token,
        admin_user_id=admin_id,
        database_path=os.getenv("DATABASE_PATH", "data/prime_era.db").strip(),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow").strip(),
    )
