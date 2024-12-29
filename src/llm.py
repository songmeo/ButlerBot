import asyncio
import json
import os

import openai
from openai import OpenAI
from evaluate import evaluate
from logger import logger

# todo: make this a class

XAI_API_KEY = os.environ["XAI_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = "gpt-4-turbo"

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
            return "Error: Missing corresponding tool_call responses for tool_call_ids."
        except Exception as e:
            logger.info(e)
            return "An unexpected error occurred."

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
        except Exception as e:
            logger.error(f"Error processing tool call: {e}")
            return "Error: Failed to process tool call."

        logger.info("tool_call and call_result messages: %s", messages)
        logger.info("bot replied: %s", completion.choices)
    return message.content