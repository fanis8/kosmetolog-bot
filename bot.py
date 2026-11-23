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


# chat_id -> message_id последнего сообщения в чате (для решения: править или отвечать новым)
_last_msg_id = {}


def _track_message(chat_id, message_id):
    _last_msg_id[chat_id] = message_id


async def _answer_callback(update, text, reply_markup=None, parse_mode="Markdown"):
    """Отвечает на нажатие кнопки: если сообщение уже не последнее — новым сообщением,
    иначе правит текущее."""
    query = update.callback_query
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    last = _last_msg_id.get(chat_id)
    if last is not None and msg_id < last:
        sent = await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        if sent:
            _track_message(chat_id, sent.message_id)
    else:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _reply_track(reply_to, text, reply_markup=None, parse_mode="Markdown"):
    """Отправляет новое сообщение и запоминает его как последнее."""
    sent = await reply_to.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    if sent:
        _track_message(reply_to.chat_id, sent.message_id)
    return sent


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    index = load_index()
    total = len(index["videos"])
    pages = len(index["pages"])

    kb = [
        [InlineKeyboardButton("🔍 Поиск по тексту", callback_data="search_text")],
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
    sent = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    if sent:
        _track_message(update.effective_chat.id, sent.message_id)


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
        await _answer_callback(update, text)
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
    await _answer_callback(update, "📂 **Выберите страницу:**", reply_markup=InlineKeyboardMarkup(menu))


async def menu_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btns = []
    for name, _ in CATEGORIES:
        btns.append(InlineKeyboardButton(name, callback_data=f"cat_{name}"))
    menu = build_menu(btns, 2)
    menu.append([InlineKeyboardButton("◀ Назад", callback_data="back_start")])
    await _answer_callback(update, "🏷 **Выберите категорию:**", reply_markup=InlineKeyboardMarkup(menu))


async def show_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = query.data.split("_", 1)[1]
    index = load_index()
    videos = find_by_page(index, page)
    if not videos:
        await _answer_callback(update, f"Страница {page} не найдена.")
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
    await _answer_callback(update, text, reply_markup=InlineKeyboardMarkup(menu))


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
        await _answer_callback(update, "Категория не найдена.")
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
        await _answer_callback(update, f"По категории «{cat_name}» ничего не найдено.")
        return

    text = f"🏷 **{cat_name}** — {len(results)} видео\n\n"
    btns = []
    for v in results:
        text += f"  Стр.{v['page']} — {v['desc']}\n"
        btns.append(InlineKeyboardButton(f"Стр.{v['page']} — {v['desc']}", callback_data=f"vid_{v['page']}_{v['seq']}"))
    menu = build_menu(btns, 1)
    menu.append([InlineKeyboardButton("◀ К категориям", callback_data="menu_categories")])
    menu.append([InlineKeyboardButton("◀ На главную", callback_data="back_start")])
    await _answer_callback(update, text, reply_markup=InlineKeyboardMarkup(menu))


async def show_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    page, seq = parts[1], int(parts[2])
    index = load_index()
    v = find_one(index, page, seq)
    if not v:
        await _answer_callback(update, "Видео не найдено.")
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
    await _answer_callback(update, text, reply_markup=InlineKeyboardMarkup(build_menu(btns, 1)))


async def back_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index = load_index()
    total = len(index["videos"])
    pages = len(index["pages"])
    kb = [
        [InlineKeyboardButton("🔍 Поиск по тексту", callback_data="search_text")],
        [InlineKeyboardButton("📂 По страницам", callback_data="menu_pages")],
        [InlineKeyboardButton("🏷 Категории", callback_data="menu_categories")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    text = (
        f"👋 Добро пожаловать! В базе **{total} видео** на **{pages} страницах**.\n\n"
        f"Введите текст, номер (44-1) или выберите раздел."
    )
    await _answer_callback(update, text, reply_markup=InlineKeyboardMarkup(kb))


async def search_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🔍 **Поиск по тексту**\n\n"
        "Просто напишите слово или фразу в поле ввода ниже и отправьте.\n\n"
        "Например:\n"
        "`губы`, `ботокс`, `Restylane`, `скулы`, `подбородок`\n\n"
        "Также можно искать по номеру видео в формате `44-1`."
    )
    await _answer_callback(update, text)


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
            await _reply_track(update.message, resp, reply_markup=InlineKeyboardMarkup(kb) if kb else None)
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
            await _reply_track(update.message, msg)
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
            await _reply_track(update.message, resp, reply_markup=InlineKeyboardMarkup(menu))
            return
        else:
            await _reply_track(update.message, f"❌ Страница «{page}» не найдена.")
            return

    results = search_by_text(index, text)
    if results:
        resp = f"🔍 **Результаты по «{text}»** — {len(results)}\n\n"
        btns = []
        for v in results:
            resp += f"  Стр.{v['page']} — {v['desc']}\n"
            btns.append(InlineKeyboardButton(f"Стр.{v['page']} — {v['desc']}", callback_data=f"vid_{v['page']}_{v['seq']}"))
        menu = build_menu(btns, 1)
        await _reply_track(update.message, resp, reply_markup=InlineKeyboardMarkup(menu))
    else:
        await _reply_track(
            update.message,
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
    app.add_handler(CallbackQueryHandler(search_text, pattern="^search_text$"))
    app.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(show_page, pattern=r"^page_\d+$"))
    app.add_handler(CallbackQueryHandler(show_category, pattern=r"^cat_"))
    app.add_handler(CallbackQueryHandler(show_video, pattern=r"^vid_\d+_\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


def main():
    import os
    import time
    import urllib.request
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    # Простой HTTP-сервер, чтобы Render видел открытый порт
    port = int(os.environ.get("PORT", "10000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args):
            pass

    httpd = HTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"HTTP-сервер для health-check запущен на порту {port}")

    app = build_app()

    # Настраиваем кнопку "Меню" с командами (отображается в поле ввода).
    # Используем urllib (синхронно, свой отдельный поток) вместо asyncio.run,
    # чтобы не закрывать event loop, который использует PTB для polling.
    import json
    try:
        commands = [
            {"command": "start", "description": "Начать / главное меню"},
            {"command": "help", "description": "Помощь"},
        ]
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
            data=json.dumps({"commands": commands}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print("Меню бота настроено")
    except Exception as e:
        print(f"Ошибка настройки меню: {e}")

    # Удаляем webhook, если он был (чтобы polling работал)
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true",
            timeout=30,
        )
        print("Webhook удалён")
    except Exception as e:
        print(f"Ошибка удаления webhook: {e}")

    print("Запуск через polling...")
    while True:
        try:
            app.run_polling(drop_pending_updates=True)
            break
        except Exception as e:
            print(f"Бот упал ({e}), перезапуск через 5с...")
            time.sleep(5)


if __name__ == "__main__":
    main()
