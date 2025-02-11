#!/usr/bin/env python3
# Copyright Song Meo <songmeo@pm.me>

import asyncio
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
from handler import photo_handler, store_message, generate_response
from logger import logger

load_dotenv()

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
DB_HOST = os.environ["DB_HOST"]
TOKEN = os.environ["TOKEN"]
BOT_NAME = "ButlerBot"


def main() -> None:
    application = Application.builder().token(TOKEN).build()

    for _ in range(5):
        try:
            con = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=5432,
            )
            cur = con.cursor()
            logger.info("Connection successful!")
            break  # success! no need to repeat
        except psycopg2.OperationalError as e:
            logger.error("Error while connecting to the database:", e)
            time.sleep(5)
    else:
        logger.error("Can't connect to the database. Abort.")
        exit(1)

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tg_user (
            id SERIAL PRIMARY KEY,  -- SERIAL handles auto-incrementing
            tg_id BIGINT NOT NULL UNIQUE,
            name TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO tg_user (tg_id, name)
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
            CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES tg_user(tg_id) ON DELETE CASCADE
        )
        """
    )
    con.commit()

    async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        _ = context
        sticker = update.message.sticker
        await update.message.reply_text(f"Nice sticker! It's {sticker.emoji} emoji.")

    async def error_handler(update: Update, context: CallbackContext) -> None:
        if isinstance(context.error, error.Conflict):
            logger.error("Conflict error detected: Another bot instance is likely running.")
            await asyncio.sleep(10)  # Wait before retrying
        else:
            logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)

    delaying = asyncio.Lock()

    async def delay_then_response(update, con):
        async with delaying:
            await asyncio.sleep(3)  # Wait 3 seconds for new messages
            await generate_response(update, con)

    async def text_handler_proxy(update, context):
        _ = context
        await store_message(update, con)

        if not delaying.locked():
            _ = asyncio.create_task(delay_then_response(update, con))  # run the delay in background

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler_proxy))

    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    application.add_handler(MessageHandler(filters.Sticker.ALL, sticker_handler))

    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
