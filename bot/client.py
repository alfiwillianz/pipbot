"""Discord client and module dispatch."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

import discord
from discord.ext import commands

from bot.modules.arxiv import ArxivModule
from bot.modules.base import WebModule
from bot.modules.crossref import CrossrefModule
from bot.modules.elsevier import ElsevierModule
from bot.modules.ieee import IEEEModule


LOGGER = logging.getLogger(__name__)


class WebLinkBot(commands.Bot):
    """Dispatch messages to the first configured web module that claims them."""

    def __init__(self, modules: Iterable[WebModule]) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.modules = tuple(modules)

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        for module in self.modules:
            if module.matches(message.content):
                await module.handle(message)
                break
        await self.process_commands(message)


def create_bot(modules: Iterable[WebModule] | None = None) -> WebLinkBot:
    """Build a bot, optionally replacing the default module list."""
    return WebLinkBot(
        modules if modules is not None else (ArxivModule(), IEEEModule(), ElsevierModule(), CrossrefModule())
    )


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    create_bot().run(token)
