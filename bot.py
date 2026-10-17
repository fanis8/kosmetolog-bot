import re
import json
import logging

import truststore
truststore.inject_into_ssl()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from flask import Flask, request

from config import TELEGRAM_TOKEN, TG_BOT_USERNAME, BOOK_AUTHOR, BOOK_TITLE
from video_index import load_index, find_by_page, find_one, search_by_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CATEGORIES = [
    ("Губы", ["губ", "губа"]),
    ("Ботокс", ["ботокс", "ботулотоксин"]),
    ("Носогубные складки", ["носогубн"]),
    ("Марионетки / уголки рта", ["марионетк", "уголк", "комиссур"]),
    ("Скулы / объём лица", ["скул", "объём"]),
    ("Морщины лба", ["морщин", "лоб"]),
    ("Подбородок / челюсть", ["подбородк", "челюст", "жевательн"]),
    ("Слёзная борозда", ["слёзн", "слезн"]),
]

PAGE_PATTERN = re.compile(r"^(\d+)$")
PAGE_NUM_PATTERN = re.compile(r"^(\d+)-(\d+)$")


def build_menu(buttons, cols=2):
    return [buttons[i:i+cols] for i in range(0, len(buttons), cols)]


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    index = load_index()
    total = len(index["videos"])
    pages = len(index["pages"])

    kb = [
        [InlineKeyboardButton("🔍 Поиск по тексту", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📂 По страницам", callback_data="menu_pages")],
        [InlineKeyboardButton("🏷 Категории", callback_data="menu_categories")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    text = (
        f"👋 Здравствуйте! Я — бот-помощник по видеоприложению к книге "
        f"*«{BOOK_TITLE}»* ({BOOK_AUTHOR}).\n\n"
        f"📚 В моей базе **{total} видео** на **{pages} страницах**.\n\n"
        f"**Что я умею:**\n"
        f"🔍 *Поиск по тексту* — напишите любое слово (губы, ботокс, Restylane...)\n"
        f"📂 *По страницам* — выберите страницу, увидите все её видео\n"
        f"🔢 *По номеру* — введите `44-1` (страница-номер)\n"
        f"🏷 *Категории* — готовые подборки по темам\n\n"
        f"Попробуйте!"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ **Как пользоваться ботом**\n\n"
        "• *Поиск по тексту* — просто напишите слово:\n"
        "  `губы`, `ботокс`, `Restylane`, `скулы`, `подбородок`\n\n"
        "• *По номеру видео* — введите в формате:\n"
        "  `44-1` (страница 44, видео №1)\n"
        "  Если номер неверный — бот подскажет.\n\n"
        "• *По странице* — нажмите «По страницам»\n\n"
        "• *Категории* — готовые подборки по процедурам\n\n"
        "📎 При выборе видео вы получите ссылку на Яндекс.Диск "
        "с просмотром в плеере."
    )
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


async def menu_pages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index = load_index()
    pages = sorted(index["pages"].keys(), key=int)
    btns = []
    for p in pages:
        count = len(index["pages"][p])
        btns.append(InlineKeyboardButton(f"Стр. {p} ({count})", callback_data=f"page_{p}"))
    menu = build_menu(btns, 3)
    menu.append([InlineKeyboardButton("◀ Назад", callback_data="back_start")])
    await query.edit_message_text("📂 **Выберите страницу:**", reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")


async def menu_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btns = []
    for name, _ in CATEGORIES:
        btns.append(InlineKeyboardButton(name, callback_data=f"cat_{name}"))
    menu = build_menu(btns, 2)
    menu.append([InlineKeyboardButton("◀ Назад", callback_data="back_start")])
    await query.edit_message_text("🏷 **Выберите категорию:**", reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")


async def show_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = query.data.split("_", 1)[1]
    index = load_index()
    videos = find_by_page(index, page)
    if not videos:
        await query.edit_message_text(f"Страница {page} не найдена.")
        return

    text = f"📂 **Страница {page}** — {len(videos)} видео\n\n"
    btns = []
    for v in videos:
        line = f"  {v['num']}. {v['desc']}"
        text += line + "\n"
        btns.append(InlineKeyboardButton(f"{v['num']}. {v['desc']}", callback_data=f"vid_{page}_{v['num']}"))
    menu = build_menu(btns, 1)
    menu.append([InlineKeyboardButton("◀ К страницам", callback_data="menu_pages")])
    menu.append([InlineKeyboardButton("◀ На главную", callback_data="back_start")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")


async def show_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_name = query.data.split("_", 1)[1]
    keywords = None
    for name, kw in CATEGORIES:
        if name == cat_name:
            keywords = kw
            break
    if not keywords:
        await query.edit_message_text("Категория не найдена.")
        return

    index = load_index()
    results = []
    for v in index["videos"]:
        desc_lower = v["desc"].lower()
        for kw in keywords:
            if kw in desc_lower:
                results.append(v)
                break
    if not results:
        await query.edit_message_text(f"По категории «{cat_name}» ничего не найдено.")
        return

    text = f"🏷 **{cat_name}** — {len(results)} видео\n\n"
    btns = []
    for v in results:
        text += f"  Стр.{v['page']} — {v['desc']}\n"
        btns.append(InlineKeyboardButton(f"Стр.{v['page']} — {v['desc']}", callback_data=f"vid_{v['page']}_{v['seq']}"))
    menu = build_menu(btns, 1)
    menu.append([InlineKeyboardButton("◀ К категориям", callback_data="menu_categories")])
    menu.append([InlineKeyboardButton("◀ На главную", callback_data="back_start")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")


async def show_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    page, seq = parts[1], int(parts[2])
    index = load_index()
    v = find_one(index, page, seq)
    if not v:
        await query.edit_message_text("Видео не найдено.")
        return

    text = (
        f"🎬 **{v['desc']}**\n"
        f"📄 Страница: {v['page']}\n"
        f"🔢 Номер: {v['seq']}\n"
        f"💾 Размер: {v['size_mb']} МБ\n"
    )
    btns = []
    if v.get("yandex_url"):
        btns.append(InlineKeyboardButton("▶ Смотреть на Яндекс.Диске", url=v["yandex_url"]))
    else:
        text += "\n⚠ Ссылка ещё не загружена."
    btns.append(InlineKeyboardButton("◀ Назад", callback_data=f"page_{v['page']}"))
    btns.append(InlineKeyboardButton("◀ На главную", callback_data="back_start"))
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(build_menu(btns, 1)), parse_mode="Markdown")


async def back_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index = load_index()
    total = len(index["videos"])
    pages = len(index["pages"])
    kb = [
        [InlineKeyboardButton("🔍 Поиск по тексту", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📂 По страницам", callback_data="menu_pages")],
        [InlineKeyboardButton("🏷 Категории", callback_data="menu_categories")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    text = (
        f"👋 Добро пожаловать! В базе **{total} видео** на **{pages} страницах**.\n\n"
        f"Введите текст, номер (44-1) или выберите раздел."
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    index = load_index()

    m = PAGE_NUM_PATTERN.match(text)
    if m:
        page, seq = m.group(1), int(m.group(2))
        v = find_one(index, page, seq)
        if v:
            resp = (
                f"🎬 **{v['desc']}**\n"
                f"📄 Страница: {v['page']}, №{v['seq']}\n"
                f"💾 {v['size_mb']} МБ"
            )
            kb = []
            if v.get("yandex_url"):
                kb.append([InlineKeyboardButton("▶ Смотреть", url=v["yandex_url"])])
            await update.message.reply_text(resp, reply_markup=InlineKeyboardMarkup(kb) if kb else None, parse_mode="Markdown")
            return
        else:
            page_exists = str(page) in index["pages"]
            seq_exists = False
            if page_exists:
                nums = [x["num"] for x in index["pages"][str(page)]]
                seq_exists = seq in nums
            parts_err = []
            if not page_exists:
                parts_err.append(f"страницы «{page}» не существует")
            if not seq_exists:
                parts_err.append(f"видео №{seq} на странице {page} не существует")
            msg = "❌ Ошибка: " + ", ".join(parts_err) + "."
            if not page_exists:
                pages = sorted(index["pages"].keys(), key=int)
                msg += f"\n\nДоступные страницы: {', '.join(p[:3] for p in pages)}…" if len(pages) > 10 else f"\n\nДоступные страницы: {', '.join(pages)}"
            else:
                nums = [str(x["num"]) for x in index["pages"][str(page)]]
                msg += f"\n\nНа странице {page} есть видео: {', '.join(nums)}"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

    m = PAGE_PATTERN.match(text)
    if m:
        page = m.group(1)
        videos = find_by_page(index, page)
        if videos:
            resp = f"📂 **Страница {page}** — {len(videos)} видео\n\n"
            btns = []
            for v in videos:
                resp += f"  {v['num']}. {v['desc']}\n"
                btns.append(InlineKeyboardButton(f"{v['num']}. {v['desc']}", callback_data=f"vid_{page}_{v['num']}"))
            menu = build_menu(btns, 1)
            await update.message.reply_text(resp, reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")
            return
        else:
            await update.message.reply_text(f"❌ Страница «{page}» не найдена.")
            return

    results = search_by_text(index, text)
    if results:
        resp = f"🔍 **Результаты по «{text}»** — {len(results)}\n\n"
        btns = []
        for v in results:
            resp += f"  Стр.{v['page']} — {v['desc']}\n"
            btns.append(InlineKeyboardButton(f"Стр.{v['page']} — {v['desc']}", callback_data=f"vid_{v['page']}_{v['seq']}"))
        menu = build_menu(btns, 1)
        await update.message.reply_text(resp, reply_markup=InlineKeyboardMarkup(menu), parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"❌ По запросу «{text}» ничего не найдено.\n"
            "Попробуйте: губы, ботокс, Restylane, скулы, 44-1"
        )


def build_app():
    from telegram.request import HTTPXRequest

    request = HTTPXRequest(read_timeout=30, write_timeout=30, connect_timeout=30, pool_timeout=30, httpx_kwargs={"verify": False})

    app = (Application.builder()
           .token(TELEGRAM_TOKEN)
           .request(request)
           .build())

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(menu_pages, pattern="^menu_pages$"))
    app.add_handler(CallbackQueryHandler(menu_categories, pattern="^menu_categories$"))
    app.add_handler(CallbackQueryHandler(back_start, pattern="^back_start$"))
    app.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(show_page, pattern=r"^page_\d+$"))
    app.add_handler(CallbackQueryHandler(show_category, pattern=r"^cat_"))
    app.add_handler(CallbackQueryHandler(show_video, pattern=r"^vid_\d+_\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


# --- Flask-приложение для вебхука (Render) ---
import asyncio
import threading

_app = None
_loop = None
_started = False
flask_app = Flask(__name__)


def get_app():
    global _app, _loop, _started
    if _app is None:
        _app = build_app()
        _loop = asyncio.new_event_loop()

        async def _run():
            await _app.initialize()
            await _app.start()
            _loop.run_forever()

        threading.Thread(target=_run, daemon=True).start()
        _started = True
        print("PTB Application запущен в фоне (initialize+start)")
    return _app


@flask_app.route("/", methods=["GET"])
def health():
    return "OK", 200


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    app = get_app()
    update = Update.de_json(request.get_json(force=True), app.bot)

    # Кладём апдейт в очередь — обрабатывается в фоновом asyncio-цикле
    async def _feed():
        await app.update_queue.put(update)

    future = asyncio.run_coroutine_threadsafe(_feed(), _loop)
    try:
        future.result(timeout=30)
    except Exception as e:
        print(f"Ошибка подачи update: {e}")
        return "ERR", 500
    return "OK", 200


# При старте регистрируем вебхук на Render
import os


def _register_webhook():
    import urllib.request
    import urllib.parse

    base = os.environ.get("WEBHOOK_URL", "").rstrip("/")
    if not base:
        print("WEBHOOK_URL не задан, вебхук не регистрируется")
        return
    url = f"{base}/webhook"
    data = urllib.parse.urlencode({"url": url}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        data=data,
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        print(f"Webhook зарегистрирован: {url}")
    except Exception as e:
        print(f"Ошибка регистрации webhook: {e}")


_register_webhook()

# Инициализируем PTB Application при старте (до первого запроса)
get_app()


# --- gunicorn entrypoint ---
app = flask_app
