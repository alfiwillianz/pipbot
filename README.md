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

## Browser backend (Obscura)

The IEEE browser session is created in `bot/browser.py`. By default (`BROWSER_BACKEND=obscura`) it attaches over CDP to an [Obscura](https://github.com/h4ckf0r0day/obscura) server at `OBSCURA_CDP_URL` (default `ws://127.0.0.1:9222`). If that connection fails it logs a warning and launches the bundled Chromium with the original options; `BROWSER_BACKEND=chromium` skips Obscura entirely.

Docker Compose starts the `obscura` service for you. Set `OBSCURA_CDP_TOKEN` in `.env` first (`openssl rand -hex 32`); Obscura refuses to listen beyond loopback without it. To run it by hand instead:

```sh
obscura serve --port 9222 --stealth \
  --proxy socks5://127.0.0.1:1080 --allow-private-network
```

- `--stealth`: IEEE Xplore is behind a bot-detecting WAF.
- `--proxy`: IEEE only serves PDFs to the institution's network. Launch options such as `proxy` and `headless` do not apply to an already-running Obscura, so `IEEE_SOCKS_PROXY` must be given to the server here as well.
- `--allow-private-network`: needed only because the proxy itself is on a loopback/private address; drop it if your proxy is public.
- `OBSCURA_SCRIPT_DEADLINE_MS=60000` (set in `compose.yaml`) gives the IEEE single-page app more than the default 30s.

Video recording, tracing, `storage_state`, service workers, and persistent contexts are not supported by Obscura. Nothing uses them today; anything that does must stay on the Chromium path.

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
