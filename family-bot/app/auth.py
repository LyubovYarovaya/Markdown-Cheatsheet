"""Проверка подписи Telegram Mini App (initData) и зависимость текущего юзера."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .models import User
from .services.users import get_or_create_user

MAX_AUTH_AGE = 24 * 60 * 60  # initData живёт сутки


class InvalidInitData(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age: int = MAX_AUTH_AGE) -> dict:
    """Проверяет подпись initData по алгоритму Telegram и возвращает поля.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        raise InvalidInitData("empty init data")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("no hash")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InvalidInitData("bad signature")

    auth_date = int(pairs.get("auth_date", "0") or 0)
    if max_age and (time.time() - auth_date) > max_age:
        raise InvalidInitData("expired")

    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except ValueError as exc:
            raise InvalidInitData("bad user payload") from exc
    return pairs


async def current_user(
    x_telegram_init_data: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    # Локальная разработка без Telegram: DEV_TG_ID в .env.
    if not x_telegram_init_data and settings.dev_tg_id:
        return await get_or_create_user(session, settings.dev_tg_id, first_name="Dev")

    try:
        data = verify_init_data(x_telegram_init_data or "", settings.bot_token)
    except InvalidInitData as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"init data: {exc}"
        ) from exc

    tg_user = data.get("user") or {}
    if not tg_user.get("id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user")

    return await get_or_create_user(
        session,
        tg_id=int(tg_user["id"]),
        first_name=tg_user.get("first_name", ""),
        username=tg_user.get("username"),
        language_code=tg_user.get("language_code"),
    )
