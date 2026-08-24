"""arXiv link detection, API access, and Discord rendering."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen

import discord

from bot.utils import DeletableView, render_math


ARXIV_API_URL = "https://export.arxiv.org/api/query?id_list={}"
ARXIV_URL_RE = re.compile(
    r"https?://(?:export\.)?(?:www\.)?arxiv\.org/(?:abs|pdf)/([^\s?#]+)",
    re.IGNORECASE,
)
ARXIV_ID_RE = re.compile(
    r"(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
LLM_URL = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:20128/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "oc/deepseek-v4-flash-free(max)")
LLM_TEMPERATURE = 0.1
ABSTRACT_LIMIT = 3500
PAPER_CACHE_TTL = timedelta(days=14)
ATOM = "{http://www.w3.org/2005/Atom}"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    title: str
    summary: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published: datetime | None
    abs_url: str
    pdf_url: str


def _cache_directory() -> Path:
    return Path(os.environ.get("PIPBOT_CACHE_DIR", "data/cache")) / "arxiv"


def _cache_key(arxiv_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", arxiv_id)


def _clear_expired_cache(directory: Path) -> None:
    cutoff = datetime.now(timezone.utc) - PAPER_CACHE_TTL
    for metadata_path in directory.glob("*.json"):
        if datetime.fromtimestamp(metadata_path.stat().st_mtime, timezone.utc) < cutoff:
            metadata_path.unlink(missing_ok=True)
            metadata_path.with_suffix(".pdf").unlink(missing_ok=True)


def _load_cached_paper(arxiv_id: str) -> tuple[Paper, bytes | None] | None:
    directory = _cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    _clear_expired_cache(directory)
    metadata_path = directory / f"{_cache_key(arxiv_id)}.json"
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        published = data.get("published")
        paper = Paper(
            arxiv_id=str(data["arxiv_id"]),
            title=str(data["title"]),
            summary=str(data["summary"]),
            authors=tuple(data["authors"]),
            categories=tuple(data["categories"]),
            published=datetime.fromisoformat(published) if published else None,
            abs_url=str(data["abs_url"]),
            pdf_url=str(data["pdf_url"]),
        )
        pdf_path = metadata_path.with_suffix(".pdf")
        pdf = pdf_path.read_bytes() if pdf_path.exists() else None
        if pdf is not None and not pdf.startswith(b"%PDF"):
            pdf_path.unlink(missing_ok=True)
            pdf = None
        return paper, pdf
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        metadata_path.unlink(missing_ok=True)
        metadata_path.with_suffix(".pdf").unlink(missing_ok=True)
        return None


def _save_cached_paper(paper: Paper, pdf: bytes | None) -> None:
    directory = _cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    metadata_path = directory / f"{_cache_key(paper.arxiv_id)}.json"
    metadata_path.write_text(
        json.dumps({
            "arxiv_id": paper.arxiv_id,
            "title": paper.title,
            "summary": paper.summary,
            "authors": paper.authors,
            "categories": paper.categories,
            "published": paper.published.isoformat() if paper.published else None,
            "abs_url": paper.abs_url,
            "pdf_url": paper.pdf_url,
        }),
        encoding="utf-8",
    )
    if pdf is not None:
        metadata_path.with_suffix(".pdf").write_bytes(pdf)


def extract_arxiv_id(content: str) -> str | None:
    """Return the first supported arXiv identifier in a Discord message."""
    match = ARXIV_URL_RE.search(content)
    if not match:
        return None

    identifier = match.group(1).removesuffix(".pdf").strip("/")
    return identifier if ARXIV_ID_RE.fullmatch(identifier) else None


def _text(element: ET.Element | None) -> str:
    return html.unescape(" ".join((element.text or "").split())) if element is not None else ""


def parse_api_response(payload: bytes, requested_id: str) -> Paper:
    """Parse one arXiv Atom API response."""
    root = ET.fromstring(payload)
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        raise ValueError("arXiv returned no paper for that identifier")

    raw_id = _text(entry.find(f"{ATOM}id"))
    arxiv_id = raw_id.rsplit("/", 1)[-1] or requested_id
    title = _text(entry.find(f"{ATOM}title")) or requested_id
    summary = _text(entry.find(f"{ATOM}summary"))
    authors = tuple(
        _text(author.find(f"{ATOM}name"))
        for author in entry.findall(f"{ATOM}author")
        if _text(author.find(f"{ATOM}name"))
    )
    categories = tuple(
        category.get("term", "")
        for category in entry.findall(f"{ATOM}category")
        if category.get("term")
    )
    published_text = _text(entry.find(f"{ATOM}published"))
    published = datetime.fromisoformat(published_text.replace("Z", "+00:00")) if published_text else None
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        summary=summary,
        authors=authors,
        categories=categories,
        published=published,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def fetch_paper(arxiv_id: str) -> Paper:
    request = Request(ARXIV_API_URL.format(arxiv_id), headers={"User-Agent": "ArxivEmbedBot/1.0"})
    with urlopen(request, timeout=15) as response:
        return parse_api_response(response.read(), arxiv_id)


def fetch_pdf(pdf_url: str) -> bytes:
    """Fetch and validate an arXiv PDF."""
    request = Request(pdf_url, headers={"Accept": "application/pdf", "User-Agent": "ArxivEmbedBot/1.0"})
    with urlopen(request, timeout=60) as response:
        payload = response.read()
    if not payload.startswith(b"%PDF"):
        raise ValueError("arXiv did not return a PDF")
    return payload


def generate_tldr(abstract: str) -> str | None:
    """Generate a short, evidence-bound summary from an abstract."""
    if not abstract:
        return None

    payload = {
        "model": LLM_MODEL,
        "temperature": LLM_TEMPERATURE,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Summarize scientific abstracts conservatively. Use only facts explicitly stated "
                    "in the abstract. Do not infer results, causes, numbers, or implications. "
                    "If the abstract does not support a detail, leave it out. Return one plain-text "
                    "TLDR sentence of at most 35 words, with no preamble."
                ),
            },
            {"role": "user", "content": abstract},
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
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
    content = result["choices"][0]["message"]["content"].strip()
    return content[:1024] or None


def paper_message_content(content: str, paper: Paper) -> str:
    """Replace the submitted arXiv URL while preserving the user's context."""
    match = ARXIV_URL_RE.search(content)
    if not match:
        return f"[{discord.utils.escape_markdown(paper.title)}]({paper.abs_url})"
    paper_name = discord.utils.escape_markdown(paper.title)
    return content[: match.start()] + paper_name + content[match.end() :]


def paper_embed(paper: Paper, author: discord.abc.User, tldr: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=paper.title[:256],
        url=paper.abs_url,
        description=render_math(
            paper.summary[: ABSTRACT_LIMIT - 3] + ("..." if len(paper.summary) > ABSTRACT_LIMIT else "")
        ),
        color=discord.Color.dark_red(),
    )
    embed.set_author(name=f"arXiv:{paper.arxiv_id}")
    if paper.authors:
        embed.add_field(name="Authors", value=", ".join(paper.authors)[:1024], inline=False)
    if paper.published:
        embed.add_field(name="Published", value=paper.published.strftime("%Y-%m-%d"))
    if tldr:
        embed.add_field(name="TLDR", value=render_math(tldr), inline=False)
    embed.set_footer(text=f"Posted by {author.display_name}")
    return embed


class ArxivModule:
    """Handle arXiv links; copy this module pattern for another website."""

    def matches(self, content: str) -> bool:
        return extract_arxiv_id(content) is not None

    async def handle(self, message: discord.Message) -> None:
        arxiv_id = extract_arxiv_id(message.content)
        if not arxiv_id:
            return

        try:
            cached = await asyncio.to_thread(_load_cached_paper, arxiv_id)
            if cached:
                paper, pdf = cached
            else:
                paper = await asyncio.to_thread(fetch_paper, arxiv_id)
                pdf = None
            if pdf is None:
                try:
                    pdf = await asyncio.to_thread(fetch_pdf, paper.pdf_url)
                except Exception:
                    LOGGER.exception("Failed to fetch PDF for arXiv paper %s", arxiv_id)
                await asyncio.to_thread(_save_cached_paper, paper, pdf)
            try:
                tldr = await asyncio.to_thread(generate_tldr, paper.summary)
            except Exception:
                LOGGER.exception("Failed to generate TLDR for arXiv link %s", arxiv_id)
                tldr = None
            await message.channel.send(
                content=paper_message_content(message.content, paper),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await message.channel.send(
                embed=paper_embed(paper, message.author, tldr),
                view=DeletableView(paper.abs_url, message.author.id),
                file=discord.File(BytesIO(pdf), filename=f"arxiv-{paper.arxiv_id.replace('/', '_')}.pdf") if pdf else None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await message.delete()
        except (ET.ParseError, ValueError):
            await message.reply("I couldn't find that arXiv paper.", mention_author=False)
        except Exception:
            LOGGER.exception("Failed to process arXiv link %s", arxiv_id)
            await message.reply("I couldn't retrieve that arXiv paper right now.", mention_author=False)
