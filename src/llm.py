import asyncio
import base64
import json
import os
import openai
from openai import OpenAI
from evaluate import evaluate
from logger import logger

# todo: make this a class

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = "gpt-4o"

client = OpenAI(api_key=OPENAI_API_KEY)


async def ask_ai(messages: list) -> str:
    loop = asyncio.get_running_loop()  # gain access to the scheduler

    def runs_in_background_thread():
        try:
            # noinspection PyShadowingNames
            completion = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=json.load(open("tools.json")),
            )
        except openai.BadRequestError as e:
            logger.info(f"OpenAI API error: {e}")
            raise ValueError("Missing corresponding tool_call responses for tool_call_ids.") from e
        except Exception as e:
            logger.info(f"Unexpected error: {e}")
            raise Exception("An unexpected error occurred while processing the tool call.") from e
        return completion

    completion = await loop.run_in_executor(None, runs_in_background_thread)
    message = completion.choices[0].message

    while message.tool_calls:
        tool_call = message.tool_calls[0]
        logger.info(f"Tool call message: {message}")
        arguments = json.loads(tool_call.function.arguments)
        expression = arguments["expression"]
        answer = evaluate(expression)
        function_call_result_message = {
            "role": "tool",
            "content": json.dumps({"result": answer}),
            "tool_call_id": tool_call.id,
        }
        messages = [message, function_call_result_message]
        try:
            completion = await loop.run_in_executor(None, runs_in_background_thread)
            message = completion.choices[0].message
        except ValueError as ve:
            logger.error(f"Tool call validation error: {ve}")
            return f"There is problem with our calculation tool! Please try again later."
        except Exception as e:
            logger.error(f"Unexpected error during tool call: {e}")
            return f"Unexpected error occurred. Please try again later."

        logger.info("tool_call and call_result messages: %s", messages)

    logger.info("bot replied: %s", completion.choices)

    return message.content


async def analyze_photo(update, image_path):
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    await update.message.reply_text("Analyzing your photo...")
    logger.info(f"Analyzing the photo")

    loop = asyncio.get_running_loop()

    def runs_in_background_thread():
        try:
            # noinspection PyShadowingNames
            completion = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    }
                ],
            )
            logger.info("bot replied: %s", completion.choices)
        except Exception as e:
            logger.info(f"Unexpected error: {e}")
            raise Exception("An unexpected error occurred while analyzing photo.")
        return completion

    completion = await loop.run_in_executor(None, runs_in_background_thread)
    message = completion.choices[0].message

    return message.content
