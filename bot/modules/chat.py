"""Mention-triggered conversational replies."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from urllib.request import Request, urlopen

import discord


LLM_URL = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:20128/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "cx/gpt-5.6-luna")
KAOMOJI = "(｡•̀ᴗ-)✧"
LOGGER = logging.getLogger(__name__)


def _remove_bot_mention(content: str, bot_id: int) -> str:
    return re.sub(rf"<@!?{bot_id}>", "", content).strip()


def generate_chat_reply(prompt: str, bot_id: int, history: list[dict[str, str]] | None = None) -> str:
    """Generate a friendly mention reply and guarantee a kaomoji."""
    user_prompt = _remove_bot_mention(prompt, bot_id) or "Say hello."
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.4,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Pipbot, a cute and playful assistant. Be warm, respectful, and concise. "
                    "Sound natural and human: vary your wording, acknowledge what the person said, "
                    "and do not use stiff assistant boilerplate or mention that you are an AI. "
                    "Use one or more cute kaomoji naturally anywhere in every response."
                ),
            },
            *(history or []),
            {"role": "user", "content": user_prompt},
        ],
    }
    request = Request(
        LLM_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **(
                {"Authorization": f"Bearer {api_key}"}
                if (api_key := os.environ.get("LLM_API_KEY"))
                else {}
            ),
        },
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        result = json.loads(response.read())
    reply = str(result["choices"][0]["message"]["content"]).strip()
    if KAOMOJI not in reply:
        reply = f"{reply} {KAOMOJI}"
    return reply[:1997] + "..." if len(reply) > 2000 else reply


class ChatModule:
    """Reply to messages that mention the bot."""

    def __init__(self) -> None:
        self.contexts: dict[int, list[dict[str, str]]] = {}

    async def handle(self, message: discord.Message, bot_id: int) -> None:
        prompt = _remove_bot_mention(message.content, bot_id)
        context = self.contexts.setdefault(message.channel.id, [])
        if prompt.casefold() == "!refresh":
            self.contexts.pop(message.channel.id, None)
            await message.reply(
                f"Fresh start! What would you like to talk about? {KAOMOJI}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        try:
            response = await asyncio.to_thread(generate_chat_reply, message.content, bot_id, context)
            context.extend(
                [
                    {"role": "user", "content": prompt or "Say hello."},
                    {"role": "assistant", "content": response},
                ]
            )
            del context[:-20]
            await message.reply(response, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            LOGGER.exception("Failed to generate chat reply")
            await message.reply(
                f"I couldn't think of a reply right now. {KAOMOJI}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
