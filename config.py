import os

# Токены передаются через переменные окружения (задаются в панели Render)
TELEGRAM_TOKEN = os.environ.get("BOT_TELEGRAM_TOKEN", "")
YANDEX_TOKEN = os.environ.get("BOT_YANDEX_TOKEN", "")

YANDEX_DISK_DIR = "Косметолог видео"
TG_BOT_USERNAME = None

BOOK_AUTHOR = "Теда К. Контис, Виктор Г. Лакомб"
BOOK_TITLE = "Техника косметических инъекций"