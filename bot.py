import os
import logging
import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Настройки из переменных окружения Railway
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
NEURO_API_URL = os.environ.get("NEURO_API_URL", "").strip()
NEURO_API_KEY = os.environ.get("NEURO_API_KEY", "").strip()
NEURO_MODEL = os.environ.get("NEURO_MODEL", "default").strip()


async def ask_neuro_natasha(user_query: str) -> str:
    """Отправляет запрос в API Neuro-Natasha и возвращает текстовый ответ."""
    if not NEURO_API_URL:
        return "Ошибка настройки: не задана переменная NEURO_API_URL."

    headers = {"Content-Type": "application/json"}
    if NEURO_API_KEY:
        headers["Authorization"] = f"Bearer {NEURO_API_KEY}"

    # Формат запроса для OpenAI Compatible (/v1/chat/completions)
    payload = {
        "model": NEURO_MODEL,
        "messages": [
            {"role": "user", "content": user_query}
        ],
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(NEURO_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        # Разбор ответа в формате OpenAI Compatible
        if isinstance(data, dict) and "choices" in data and data["choices"]:
            return data["choices"][0]["message"]["content"]

        # Запасной разбор для кастомного эндпоинта Chat
        if isinstance(data, dict):
            return (
                data.get("answer")
                or data.get("response")
                or data.get("text")
                or data.get("message")
                or str(data)
            )
        return str(data)


async def safe_reply(update: Update, text: str) -> None:
    """Безопасная отправка длинных сообщений частями (лимит Telegram — 4096 символов)."""
    if not update.message or not text:
        return

    max_len = 3900
    while len(text) > max_len:
        split_pos = text[:max_len].rfind("\n\n")
        if split_pos == -1:
            split_pos = text[:max_len].rfind("\n")
        if split_pos == -1:
            split_pos = max_len

        chunk = text[:split_pos].strip()
        if chunk:
            await update.message.reply_text(chunk)
        text = text[split_pos:].strip()

    if text:
        await update.message.reply_text(text)


async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_name = update.effective_user.first_name if update.effective_user else "коллега"
    welcome_text = (
        f"Здравствуйте, {user_name}! Я ваш ИИ-консультант.\n\n"
        "Задайте ваш вопрос, и я постараюсь помочь."
    )
    await update.message.reply_text(welcome_text)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_query = update.message.text.strip()
    if not user_query:
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        answer = await ask_neuro_natasha(user_query)
        await safe_reply(update, answer)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP ошибка от API ({e.response.status_code}): {e.response.text}")
        await update.message.reply_text(
            "Сервер временно вернул ошибку. Попробуйте повторить вопрос чуть позже."
        )
    except Exception as e:
        logger.error(f"Ошибка при обращении к API: {e}")
        await update.message.reply_text(
            "Извините, возникла техническая заминка. Пожалуйста, повторите вопрос через несколько секунд."
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка при обработке обновления Telegram:", exc_info=context.error)


def main() -> None:
    if not TELEGRAM_TOKEN:
        logger.critical("Переменная TELEGRAM_TOKEN не задана!")
        return

    req = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = Application.builder().token(TELEGRAM_TOKEN).request(req).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен и слушает сообщения Telegram...")
    app.run_polling(
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
    )


if __name__ == "__main__":
    main()
