"""Discord helpers shared by web-link modules."""

from __future__ import annotations

import re
import json
import os
import unicodedata
from urllib.request import Request, urlopen

import discord
from unicodeitplus import replace as replace_unicode_math


MATH_SPAN_RE = re.compile(r"\$(?!\$)(.+?)(?<!\\)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.DOTALL)


def render_math(text: str) -> str:
    """Render delimited LaTeX as Unicode without changing surrounding prose."""
    def convert(match: re.Match[str]) -> str:
        source = next(group for group in match.groups() if group is not None)
        source = re.sub(r"\\widetilde\{([^{}]+)\}", r"\\tilde \1", source)
        source = re.sub(r"\\text\{([^{}]+)\}", r"\1", source)
        try:
            converted = replace_unicode_math(source)
            return re.sub(r"\\(log|ln|exp|max|min)", r"\1", converted)
        except Exception:
            return source

    rendered = MATH_SPAN_RE.sub(convert, text)
    needs_fallback = any(char in rendered for char in ("\\", "{", "}", "^")) or any(
        unicodedata.combining(char) for char in rendered
    )
    if rendered == text or not needs_fallback:
        return rendered

    base_url = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not base_url or not model:
        return rendered
    payload = {
        "model": model,
        "temperature": 0,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Convert only LaTeX math to readable Unicode. Preserve all prose and mathematical "
                    "meaning exactly. Return only the converted text."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key := os.environ.get("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = Request(base_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
        fallback = str(result["choices"][0]["message"]["content"]).strip()
        return fallback or rendered
    except Exception:
        return rendered


class DeletableView(discord.ui.View):
    """View with a link button and a permission-aware delete button."""

    def __init__(self, url: str, source_author_id: int) -> None:
        super().__init__(timeout=None)
        self.source_author_id = source_author_id
        self.add_item(discord.ui.Button(label="Open", style=discord.ButtonStyle.link, url=url))

    def can_delete(self, user: discord.abc.User) -> bool:
        if user.id == self.source_author_id:
            return True
        return isinstance(user, discord.Member) and user.guild_permissions.manage_messages

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="web-link:delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.can_delete(interaction.user):
            await interaction.response.send_message(
                "Only the original poster or a member with Manage Messages can delete this.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        if interaction.message:
            await interaction.message.delete()
