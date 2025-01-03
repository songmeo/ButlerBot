#!/usr/bin/env python3
# Copyright Song Meo <songmeo@pm.me>
import time

import psycopg2
import os

from dotenv import load_dotenv
from telegram import Update, error
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackContext,
)
from llm import ask_ai
from logger import logger

load_dotenv()

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
DB_HOST = os.environ["DB_HOST"]
TOKEN = os.environ["TOKEN"]
BOT_NAME = "ButlerBot"


async def echo(
    update: Update, context: ContextTypes.DEFAULT_TYPE, con: psycopg2.connect
) -> None:
    _ = context
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
        """
        INSERT INTO "user" (tg_id, name)
        VALUES (%s, %s)
        ON CONFLICT (tg_id) DO NOTHING
        """,
        (user_id, username),
    )
    cur.execute(
        """
        INSERT INTO user_message (chat_id, user_id, message)
        VALUES (%s, %s, %s)
        """,
        (chat_id, user_id, text),
    )
    con.commit()
    no_reply_token = "-"
    messages = [
        {
            "role": "system",
            "content": f"Each message in the conversation below is prefixed with the username and their unique "
            'identifier, like this: "username (123456789): MESSAGE...". '
            f"You play the role of the user called {BOT_NAME}, or simply Bot; "
            f"your username and unique identifier are {BOT_NAME} and 0. "
            f"You are observing the users' conversation and normally you do not interfere "
            f"unless you are explicitly called by name (e.g., 'bot,' '{BOT_NAME},' etc.). "
            f"Explicit mentions include cases where your name or identifier appears anywhere in the message. "
            f"If you are not explicitly addressed, always respond with {no_reply_token}.",
        },
    ]
    cur.execute(
        """
        SELECT 
            user_message.user_id,
            "user".name AS username,
            user_message.message
        FROM 
            user_message
        JOIN
            "user"
        ON 
            user_message.user_id = "user".tg_id
        WHERE 
            user_message.chat_id = %s
        ORDER BY 
            user_message.id
        LIMIT 1000;
        """,
        (chat_id,),
    )
    all_messages = cur.fetchall()
    for user_id, user_name, message in all_messages:
        messages.append(
            {
                "role": "assistant" if user_id == 0 else "user",
                "content": f"{user_name} ({user_id}): {message}",
            }
        )
    try:
        response = await ask_ai(messages)
        logger.info("all messages: %s", messages)
    except Exception as e:
        logger.error(f"Error while calling the LLM: {e}")
        return

    response = response.removeprefix(f"{BOT_NAME} (0): ")
    if response != no_reply_token:
        cur.execute(
            """
            INSERT INTO user_message (chat_id, user_id, message)
            VALUES (%s, 0, %s)
            """,
            (chat_id, response),
        )
        await update.message.reply_text(response)
    else:
        logger.info("The bot has nothing to say.")
    con.commit()


def main() -> None:
    application = Application.builder().token(TOKEN).build()

    con = psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=5432
    )
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS "user" (
            id SERIAL PRIMARY KEY,  -- SERIAL handles auto-incrementing
            tg_id BIGINT NOT NULL UNIQUE,
            name TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO "user" (tg_id, name)
        VALUES (%s, %s)
        ON CONFLICT (tg_id) DO NOTHING
        """,
        (0, BOT_NAME),
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_message (
            id SERIAL PRIMARY KEY,  -- SERIAL handles auto-incrementing
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            message TEXT NOT NULL,
            CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES "user"(tg_id) ON DELETE CASCADE
        )
        """
    )
    con.commit()

    async def echo_proxy(update, context):
        await echo(update, context, con)

    # on non command i.e. text message
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_proxy))

    async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        _ = context
        sticker = update.message.sticker
        await update.message.reply_text(f"Nice sticker! It's {sticker.emoji} emoji.")

    # on stickers
    application.add_handler(MessageHandler(filters.Sticker.ALL, sticker_handler))

    async def error_handler(update: Update, context: CallbackContext) -> None:
        if isinstance(context.error, error.Conflict):
            logger.error(
                "Conflict error detected: Another bot instance is likely running."
            )
            await application.bot.delete_webhook(drop_pending_updates=True)
            time.sleep(10)  # Wait before retrying (adjust as needed)
        else:
            logger.error(
                f"Update {update} caused error {context.error}", exc_info=context.error
            )

    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
