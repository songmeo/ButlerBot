#!/usr/bin/env python3

import logging
import sqlite3
import os
from openai import OpenAI
from dotenv import load_dotenv
from telegram import ForceReply, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

XAI_API_KEY = os.environ["XAI_API_KEY"]
OpenAI_API_KEY = os.environ["OpenAI_API_KEY"]
TOKEN = os.environ["TOKEN"]

client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1/")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Define a few command handlers. These usually take the two arguments update and
# context.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text("Help!")


def ask_ai(question: str, messages: list) -> str:
    completion = client.chat.completions.create(model="grok-beta", messages=messages)
    answer = completion.choices[0].message.content
    return answer


async def echo(
    update: Update, context: ContextTypes.DEFAULT_TYPE, con: sqlite3.Connection
) -> None:
    """Echo the user message."""
    logger.info(
        "Mew message from chat %s, user %s",
        update.message.chat_id,
        update.message.from_user.id,
    )
    text = update.message.text
    cur = con.cursor()
    chat_id, user_id, username = (
        update.message.chat_id,
        update.message.from_user.id,
        update.message.from_user.username,
    )
    cur.execute(
        "INSERT OR IGNORE INTO user VALUES (NULL,?,?)",
        (user_id, username),
    )
    cur.execute(
        "INSERT INTO user_message VALUES (NULL,?,?,?)",
        (chat_id, user_id, text),
    )
    con.commit()
    no_reply_token = "-"
    messages = [
        {
            "role": "system",
            "content": "Each message in the conversation below is prefixed with the username and their"
            ' unique identifier, like this: "username (123456789): MESSAGE...".'
            " You play the role of the user called ButlerBot, or simply Bot;"
            " your username and unique identifier are ButlerBot and 0."
            " You are observing the user's conversation and normally you do not interfere unless you are"
            " contextually expected to, you can contribute to the conversation, or if you are addressed "
            " directly."
            f' If you have nothing to say, respond with "{no_reply_token}".',
        },
    ]
    all_messages = cur.execute(
        """
        SELECT 
            user_message.user_id,
            user.name AS username,
            user_message.message
        FROM 
            user_message 
        JOIN
            user
        ON 
            user_message.user_id = user.tg_id 
        WHERE 
            user_message.chat_id = ? 
        ORDER BY 
            user_message.id 
        LIMIT 1000;
        """,
        (chat_id,),
    ).fetchall()
    for user_id, user_name, message in all_messages:
        messages.append(
            {
                "role": "assistant" if user_id == 0 else "user",
                "content": f"{user_name} ({user_id}): {message}",
            }
        )
    answer = ask_ai(text, messages).removeprefix("ButlerBot (0): ")
    if answer != no_reply_token:
        cur.execute(  # id, user_id, chat_id, message
            "INSERT INTO user_message VALUES (NULL,?,0,?)",
            (chat_id, answer),
        )
        await update.message.reply_text(answer)
    else:
        logger.info("The bot has nothing to say.")
    con.commit()


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    con = sqlite3.connect("telegrambot.db")

    async def echo_proxy(update, context):
        await echo(update, context, con)

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, echo_proxy))

    cur = con.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS user("
        "id       INTEGER PRIMARY KEY,"
        "tg_id    INTEGER NOT NULL UNIQUE,"
        "name     TEXT"
        ")"
    )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS user_message("
        "id         INTEGER PRIMARY KEY,"
        "chat_id    INTEGER NOT NULL,"
        "user_id    INTEGER NOT NULL,"
        "message    TEXT NOT NULL,"
        "CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES user(tg_id)"
        ")"
    )
    con.commit()

    async def echo_proxy(update, context):
        await echo(update, context, con)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
