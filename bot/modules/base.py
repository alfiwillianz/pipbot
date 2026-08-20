"""Interfaces for modules that handle links from different websites."""

from __future__ import annotations

from typing import Protocol

import discord


class WebModule(Protocol):
    """A module that can claim and process a Discord message."""

    def matches(self, content: str) -> bool:
        ...

    async def handle(self, message: discord.Message) -> None:
        ...
