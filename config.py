import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "0") or "0")
HH_LOGIN = os.getenv("HH_LOGIN", "").strip()

AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "false").lower() == "true"
SEARCH_INTERVAL_MINUTES = int(os.getenv("SEARCH_INTERVAL_MINUTES", "30"))
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "30"))
MAX_DAILY_APPLIES = int(os.getenv("MAX_DAILY_APPLIES", "10"))

HH_AREA_MOSCOW = os.getenv("HH_AREA_MOSCOW", "1")
HH_AREA_SPB = os.getenv("HH_AREA_SPB", "2")

COVER_LETTER = os.getenv(
    "COVER_LETTER",
    "Добрый день. Рассматриваю управленческую роль в продажах и рознице. "
    "Готов обсудить, какую задачу могу решить у вас."
).strip()

COOKIES_PATH = DATA_DIR / "hh_cookies.json"
DB_PATH = DATA_DIR / "bot.sqlite3"

TARGET_QUERIES = [
    "директор розничной сети",
    "коммерческий директор",
    "директор по продажам",
    "региональный директор",
    "операционный директор",
    "руководитель отдела продаж",
    "head of sales",
]

EXCLUDE_TITLE_PARTS = [
    "продавец", "продавец-консультант", "администратор магазина",
    "стажер", "стажёр", "ассистент", "помощник",
    "менеджер по продажам", "оператор", "кассир",
]
