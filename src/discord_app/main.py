import asyncio
import logging
import uvicorn
from discord_app.config import load_settings
from discord_app.logger import setup_logging
from discord_app.discord_bot import create_bot
from discord_app import webhook

async def run():
    setup_logging()
    settings = load_settings()
    logging.getLogger(__name__).info("Starting with DB at %s", settings.db_path)

    bot = await create_bot(settings)

    # Run FastAPI server and Discord bot concurrently
    config = uvicorn.Config(webhook.app, host="0.0.0.0", port=settings.port, log_level="info")
    server = uvicorn.Server(config)

    async def start_web():
        await server.serve()

    async def start_bot():
        await bot.start(settings.discord_token)

    await asyncio.gather(start_web(), start_bot())

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
