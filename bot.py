import os
import base64
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from openai import OpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not found in .env")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not found in .env")

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Ты дружелюбный ИИ-помощник в Telegram. Отвечай по-русски, кратко и по делу. "
    "Если пользователь просит картинку — попроси написать /img и описание."
)

# Простая память: храним последние сообщения на пользователя
USER_HISTORY: dict[int, list[dict]] = {}
MAX_TURNS = 10  # 10 последних сообщений (user+assistant)

def get_history(user_id: int) -> list[dict]:
    return USER_HISTORY.get(user_id, [])

def add_to_history(user_id: int, role: str, content: str) -> None:
    hist = USER_HISTORY.get(user_id, [])
    hist.append({"role": role, "content": content})
    # ограничим длину
    if len(hist) > MAX_TURNS * 2:
        hist = hist[-MAX_TURNS * 2 :]
    USER_HISTORY[user_id] = hist


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я AI-бот 🤖\n\n"
        "• Просто пиши текст — отвечу как ChatGPT\n"
        "• Картинки: /img описание\n"
        "Пример: /img фотореалистичный портрет, студийный свет"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Команды:\n"
        "/start — старт\n"
        "/help — помощь\n"
        "/img <описание> — сгенерировать изображение\n"
        "/reset — очистить память диалога"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    USER_HISTORY.pop(update.effective_user.id, None)
    await update.message.reply_text("Память диалога очищена ✅")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    user_id = update.effective_user.id

    # покажем "печатает..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # собираем контекст
    history = get_history(user_id)

    # вызов Responses API
    try:
        resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=hist(uid) + [{"role": "user", "content": text}],
    )

        answer = (resp.choices[0].message.content or "").strip() or "Не понял 😅"
    except Exception as e:
        await update.message.reply_text(f"Ошибка OpenAI: {e}")
        return

    add_to_history(user_id, "user", user_text)
    add_to_history(user_id, "assistant", answer)

    await update.message.reply_text(answer)


async def img(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Напиши так: /img описание картинки")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")

    try:
        # Генерация изображения через Responses API (возвращаем base64)
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"Сгенерируй изображение: {prompt}"},
                ],
            }],
        )

        # Достаём первое изображение из ответа
        b64 = None
        for item in resp.output:
            if item.type == "message":
                for c in item.content:
                    # В разных версиях SDK поля могут отличаться;
                    # чаще всего для изображений приходит "output_image" с base64.
                    if getattr(c, "type", None) in ("output_image", "image"):
                        b64 = getattr(c, "b64_json", None) or getattr(c, "image_base64", None)
                        if b64:
                            break
            if b64:
                break

        if not b64:
            await update.message.reply_text("Не смог получить картинку из ответа 😅 Попробуй другое описание.")
            return

        image_bytes = base64.b64decode(b64)
        await update.message.reply_photo(photo=image_bytes, caption="Готово ✅")

    except Exception as e:
        await update.message.reply_text(f"Ошибка генерации изображения: {e}")


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("img", img))

    # обычные сообщения — в чат
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()


