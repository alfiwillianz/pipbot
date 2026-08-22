# Pipbot

This bot watches messages for web links and dispatches them to modular handlers. The included arXiv module fetches metadata from the arXiv API, posts an embed with the title, abstract, authors, and buttons, then removes the original message.

## Local Setup

1. Create a virtual environment and install dependencies:

   ```sh
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a Discord application and bot, then enable the **Message Content Intent**.
3. Invite the bot with the `View Channel`, `Send Messages`, `Embed Links`, `Read Message History`, and `Manage Messages` permissions.
4. Set `DISCORD_TOKEN` from `.env.example` in the bot's environment and run:

   ```sh
   python -m bot
   ```

Run those commands from this `pipbot/` directory. With the existing Conda environment:

```sh
mamba activate bot
python -m bot
```

The embed currently includes the title, abstract, authors, publication date, and arXiv source categories. TLDR generation is intentionally not included until an LLM endpoint is configured. The **Open paper** button is a native Discord link button. The **Delete** button can be used only by the person who posted the original link or a member with `Manage Messages`.

IEEE PDFs are attached through a Playwright browser session that preserves IEEE's temporary WAF cookies. arXiv PDFs are fetched directly from arXiv. Both paper types are cached under `PIPBOT_CACHE_DIR` and deleted after 14 days. The IEEE HTTP fallback can use `IEEE_PDF_COOKIE` with a current browser Cookie header, but the cookie is temporary and must be kept out of git. PDF attachment is skipped if the source rejects the request.

## Adding a module

Add a class under `bot/modules/` implementing the `WebModule` protocol:

```python
class ExampleModule:
    def matches(self, content: str) -> bool:
        return "example.com" in content

    async def handle(self, message: discord.Message) -> None:
        # Fetch metadata, send an embed, and delete the original message.
        ...
```

Register it in `bot/client.py` by adding an instance to `create_bot()` alongside `ArxivModule()`. Shared buttons and permission checks are in `bot/utils.py`.

## Docker Compose

Create `pipbot/.env` from `.env.example`, set `DISCORD_TOKEN`, then run:

```sh
docker compose up --build -d
```

Stop it with:

```sh
docker compose down
```
