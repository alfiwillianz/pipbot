"""IEEE Xplore link detection, metadata access, and Discord rendering."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import discord

from bot.modules.arxiv import ABSTRACT_LIMIT, generate_tldr
from bot.utils import DeletableView


IEEE_URL_RE = re.compile(
    r"https?://(?:www\.)?ieeexplore\.ieee\.org/(?:abstract/)?document/(\d+)",
    re.IGNORECASE,
)
IEEE_API_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
IEEE_API_KEY = os.environ.get("IEEE_API_KEY", "")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IEEEArticle:
    article_number: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    publication_date: str
    doi: str
    url: str


def extract_ieee_article_number(content: str) -> str | None:
    """Return the first IEEE Xplore article number in a message."""
    match = IEEE_URL_RE.search(content)
    return match.group(1) if match else None


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = []
    for author in value:
        if isinstance(author, dict):
            name = author.get("full_name") or author.get("name")
        else:
            name = author
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)


def parse_ieee_response(payload: bytes, article_number: str) -> IEEEArticle:
    """Parse one IEEE Metadata API response."""
    result = json.loads(payload)
    articles = result.get("articles", [])
    if not articles:
        raise ValueError("IEEE returned no paper for that article number")

    article = articles[0]
    resolved_number = str(article.get("article_number") or article_number)
    return IEEEArticle(
        article_number=resolved_number,
        title=str(article.get("title") or resolved_number),
        abstract=str(article.get("abstract") or ""),
        authors=_authors(article.get("authors")),
        publication_date=str(article.get("publication_date") or article.get("publication_year") or ""),
        doi=str(article.get("doi") or ""),
        url=f"https://ieeexplore.ieee.org/document/{resolved_number}",
    )


def fetch_article(article_number: str) -> IEEEArticle:
    if not IEEE_API_KEY:
        raise RuntimeError("IEEE_API_KEY is required")
    query = urlencode({"apikey": IEEE_API_KEY, "article_number": article_number, "format": "json"})
    request = Request(f"{IEEE_API_URL}?{query}", headers={"User-Agent": "Pipbot/1.0"})
    with urlopen(request, timeout=15) as response:
        return parse_ieee_response(response.read(), article_number)


def article_message_content(content: str, article: IEEEArticle) -> str:
    """Replace the submitted IEEE URL while preserving the user's context."""
    match = IEEE_URL_RE.search(content)
    article_link = discord.utils.escape_markdown(article.title)
    if not match:
        return article_link
    return content[: match.start()] + article_link + content[match.end() :]


def article_embed(article: IEEEArticle, author: discord.abc.User, tldr: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=article.title[:256],
        url=article.url,
        description=article.abstract[: ABSTRACT_LIMIT - 3] + ("..." if len(article.abstract) > ABSTRACT_LIMIT else ""),
        color=discord.Color.blue(),
    )
    embed.set_author(name=f"IEEE:{article.article_number}")
    if article.authors:
        embed.add_field(name="Authors", value=", ".join(article.authors)[:1024], inline=False)
    if article.publication_date:
        embed.add_field(name="Published", value=article.publication_date)
    if tldr:
        embed.add_field(name="TLDR", value=tldr, inline=False)
    embed.set_footer(text=f"Posted by {author.display_name}")
    return embed


class IEEEModule:
    """Handle IEEE Xplore document links."""

    def matches(self, content: str) -> bool:
        return extract_ieee_article_number(content) is not None

    async def handle(self, message: discord.Message) -> None:
        article_number = extract_ieee_article_number(message.content)
        if not article_number:
            return

        try:
            article = await asyncio.to_thread(fetch_article, article_number)
            try:
                tldr = await asyncio.to_thread(generate_tldr, article.abstract)
            except Exception:
                LOGGER.exception("Failed to generate TLDR for IEEE article %s", article_number)
                tldr = None
            await message.channel.send(
                content=article_message_content(message.content, article),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await message.channel.send(
                embed=article_embed(article, message.author, tldr),
                view=DeletableView(article.url, message.author.id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await message.delete()
        except (json.JSONDecodeError, ValueError):
            await message.reply("I couldn't find that IEEE paper.", mention_author=False)
        except Exception:
            LOGGER.exception("Failed to process IEEE article %s", article_number)
            await message.reply("I couldn't retrieve that IEEE paper right now.", mention_author=False)
