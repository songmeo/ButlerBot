import asyncio
import uuid
import urllib.request
import psycopg2
import os
from telegram import Update
from telegram.ext import (
    ContextTypes,
    CallbackContext,
)
from llm import ask_ai, analyze_photo
from logger import logger

BOT_NAME = "ButlerBot"
no_reply_token = "-"
SYSTEM_PROMPT = f"""
    Each message in the conversation below is prefixed with the username and their unique 
    identifier, like this: "username (123456789): MESSAGE...". '
    You play the role of the user called {BOT_NAME}, or simply Bot;
    your username and unique identifier are {BOT_NAME} and 0. 
    You are observing the users' conversation and normally you do not interfere 
    unless you are explicitly called by name (e.g., 'bot,' '{BOT_NAME},' etc.). 
    Explicit mentions include cases where your name or identifier appears anywhere in the message. 
    If you are not explicitly addressed, always respond with {no_reply_token}.
    When answering, don't use LaTeX.
    """


async def store_message(update: Update, con: psycopg2.connect) -> None:
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
        INSERT INTO tg_user (tg_id, name)
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


async def generate_response(update: Update, con: psycopg2.connect):
    cur = con.cursor()
    chat_id = update.message.chat_id
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    cur.execute(
        """
        SELECT 
            user_message.user_id,
            tg_user.name AS username,
            user_message.message
        FROM 
            user_message
        JOIN
            tg_user
        ON 
            user_message.user_id = tg_user.tg_id
        WHERE 
            user_message.chat_id = %s
        ORDER BY 
            user_message.id ASC
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


async def photo_handler(update: Update, context: CallbackContext) -> None:
    try:
        file_id = update.message.photo[-1].file_id
        file_info = await context.bot.get_file(file_id)
        file_path = file_info.file_path

        file_name = f"{uuid.uuid4()}.jpg"

        loop = asyncio.get_running_loop()

        def runs_in_background_thread():
            try:
                with urllib.request.urlopen(file_path) as response:
                    if response.status == 200:
                        with open(file_name, "wb") as f:
                            f.write(response.read())
                        logger.info(f"File downloaded successfully: {file_name}")
                    else:
                        logger.error(f"Failed to download the file. Status code: {response.status}")
            except Exception as e:
                logger.error(f"Unexpected error while downloading the file: {e}")

        # Run the blocking function in a separate thread
        await loop.run_in_executor(None, runs_in_background_thread)

        response = await analyze_photo(update, file_name)

        if os.path.exists(file_name):
            os.remove(file_name)

        await update.message.reply_text(response)

    except Exception as e:
        raise Exception(f"An unexpected error {e}")
