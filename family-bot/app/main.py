from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import runtime
from .api.core import router as core_router
from .api.expenses import router as expenses_router
from .api.public import router as public_router
from .bot import COMMANDS, get_bot, get_dispatcher
from .config import settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("family-bot")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


async def _start_bot(app: FastAPI) -> None:
    if settings.bot_mode == "off" or not settings.bot_token:
        log.warning("Бот не запущен: BOT_MODE=off или пустой BOT_TOKEN")
        return

    bot = get_bot()
    try:
        me = await bot.get_me()
    except Exception as error:
        # Неверный токен или нет интернета — не роняем весь процесс: веб-часть
        # пусть живёт, а человеку показываем внятную причину вместо трейсбека.
        log.error(
            "Не получилось подключиться к Telegram: %s\n"
            "Проверь BOT_TOKEN в .env и интернет, потом перезапусти. "
            "Веб-приложение пока работает, бот — нет.",
            error,
        )
        return
    runtime.bot_username = me.username
    await bot.set_my_commands(COMMANDS)
    log.info("Бот @%s готов, режим %s", me.username, settings.bot_mode)

    if settings.bot_mode == "webhook":
        await bot.set_webhook(
            f"{settings.base_url}/telegram/webhook",
            secret_token=settings.webhook_secret,
            drop_pending_updates=True,
        )
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        dispatcher = get_dispatcher()
        app.state.polling_task = asyncio.create_task(dispatcher.start_polling(bot))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _start_bot(app)
    try:
        yield
    finally:
        task = getattr(app.state, "polling_task", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        with contextlib.suppress(Exception):
            await get_bot().session.close()


app = FastAPI(title="Family Hub", lifespan=lifespan, docs_url="/api/docs")
app.include_router(core_router)
app.include_router(expenses_router)
app.include_router(public_router)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="bad secret")
    update = Update.model_validate(await request.json(), context={"bot": get_bot()})
    await get_dispatcher().feed_update(get_bot(), update)
    return JSONResponse({"ok": True})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "bot": runtime.bot_username}


@app.get("/s/{token}")
async def share_page(token: str) -> FileResponse:
    """Публичная страница списка — открывается в любом браузере, без Telegram."""
    return FileResponse(WEB_DIR / "share.html")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="webapp")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
