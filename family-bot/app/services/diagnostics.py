"""Проверка, доступно ли приложение снаружи по своему публичному адресу."""

from __future__ import annotations

import socket
from urllib.parse import urlparse

import httpx


async def probe(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Стучится по адресу и возвращает (получилось, объяснение по-человечески)."""
    host = urlparse(url).hostname
    if not host:
        return False, "адрес выглядит неправильно"

    try:
        await _resolve(host)
    except OSError:
        return False, "домен не резолвится — туннель выключен или адрес устарел"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.ConnectTimeout:
        return False, "домен есть, но никто не отвечает — туннель поднят, а приложение нет"
    except httpx.HTTPError as error:
        return False, f"не достучалась: {type(error).__name__}"

    if response.status_code >= 500:
        return False, f"приложение отвечает ошибкой {response.status_code}"
    if response.status_code >= 400:
        return False, f"страница не найдена ({response.status_code})"
    return True, "отвечает"


async def _resolve(host: str) -> None:
    import asyncio

    await asyncio.to_thread(socket.getaddrinfo, host, None)
