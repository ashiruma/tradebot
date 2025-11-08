"""
Healthcheck API for the trading bot.
Run separately or as part of the bot to expose status on localhost:8080/health
"""

from aiohttp import web
from datetime import datetime
from config import ENABLE_TRADING, DRY_RUN

bot_status = {
    "status": "initializing",
    "last_update": datetime.utcnow().isoformat(),
    "mode": "DRY_RUN" if DRY_RUN or not ENABLE_TRADING else "LIVE",
    "running": False,
}


async def handle_health(request):
    bot_status["last_update"] = datetime.utcnow().isoformat()
    return web.json_response(bot_status)


async def run_health_server():
    app = web.Application()
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("✅ Healthcheck server running at http://localhost:8080/health")
    while True:
        await web.sleep(60)
