#!/usr/bin/env python3
"""Диагностика: почему не открывается мини-приложение.

Запуск из папки family-bot:  python3 doctor.py   (Windows: py doctor.py)
Ничего не чинит — только проверяет и говорит, что делать. Нужен только
стандартный Python, виртуальное окружение не требуется.
"""

from __future__ import annotations

import json
import pathlib
import platform
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent
TIMEOUT = 10

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if platform.system() == "Windows":  # старые консоли не понимают ANSI
    GREEN = RED = YELLOW = DIM = OFF = ""

problems: list[str] = []


def ok(text: str) -> None:
    print(f"{GREEN}✓{OFF} {text}")


def bad(text: str, advice: str = "") -> None:
    print(f"{RED}✗{OFF} {text}")
    if advice:
        problems.append(advice)


def note(text: str) -> None:
    print(f"{YELLOW}!{OFF} {text}")


def read_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        bad("Файла .env нет", "Запусти ./start.sh — он создаст .env и спросит токен.")
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def fetch(url: str) -> tuple[int | None, str]:
    """Возвращает (код ответа, текст или причина ошибки)."""
    request = urllib.request.Request(url, headers={"User-Agent": "family-bot-doctor"})
    # До своей же машины ходим мимо системного прокси, иначе корпоративный
    # прокси может «не найти» localhost и мы решим, что приложение лежит.
    is_local = (urlparse(url).hostname or "") in {"localhost", "127.0.0.1", "::1"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if is_local else None
    try:
        open_url = opener.open if opener else urllib.request.urlopen
        with open_url(request, timeout=TIMEOUT) as response:
            return response.status, response.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.reason or ""
    except urllib.error.URLError as error:
        return None, str(error.reason)
    except (TimeoutError, socket.timeout):
        return None, "таймаут"
    except OSError as error:
        return None, str(error)


def tunnel_processes() -> list[str]:
    try:
        if platform.system() == "Windows":
            output = subprocess.run(
                ["tasklist"], capture_output=True, text=True, timeout=10
            ).stdout.lower()
            return [name for name in ("cloudflared", "ngrok") if name in output]
        output = subprocess.run(["ps", "ax"], capture_output=True, text=True, timeout=10).stdout.lower()
        return [name for name in ("cloudflared", "ngrok") if name in output]
    except (OSError, subprocess.SubprocessError):
        return []


def main() -> int:
    print(f"\n{DIM}Проверяю установку в {ROOT}{OFF}\n")
    env = read_env()
    if not env:
        return report()

    # 1. Настройки
    token = env.get("BOT_TOKEN", "")
    if not token or token.startswith("123456:ABC-DEF"):
        bad("BOT_TOKEN не заполнен", "Возьми токен у @BotFather и впиши в .env (или перезапусти ./start.sh).")
    else:
        ok(f"BOT_TOKEN на месте ({token.split(':')[0]}:…)")

    public_url = env.get("PUBLIC_URL", "").rstrip("/")
    port = env.get("PORT", "8080")
    print(f"  {DIM}PUBLIC_URL = {public_url or 'пусто'}{OFF}")
    print(f"  {DIM}PORT       = {port}{OFF}")
    if env.get("NGROK_DOMAIN"):
        print(f"  {DIM}NGROK_DOMAIN = {env['NGROK_DOMAIN']}{OFF}")

    # 2. Приложение на своей машине
    status, _ = fetch(f"http://localhost:{port}/healthz")
    if status == 200:
        ok(f"Приложение работает на localhost:{port}")
    else:
        bad(
            f"На localhost:{port} никто не отвечает",
            "Приложение не запущено. Запусти ./start.sh и оставь окно терминала открытым.",
        )

    # 3. Туннель
    running = tunnel_processes()
    if running:
        ok(f"Процесс туннеля найден: {', '.join(running)}")
    else:
        note("Процессов cloudflared/ngrok не видно")

    # 4. Публичный адрес
    if not public_url.startswith("https://"):
        bad(
            f"PUBLIC_URL не https ({public_url or 'пусто'})",
            "Telegram открывает мини-приложение только по https. Запусти ./start.sh — "
            "он поднимет туннель и сам впишет адрес.",
        )
        return report()

    host = urlparse(public_url).hostname or ""
    try:
        socket.getaddrinfo(host, None)
        ok(f"Домен {host} резолвится")
    except OSError:
        bad(
            f"Домен {host} не существует",
            "Адрес в .env устарел: туннель перезапускался и выдал новый. "
            "Перезапусти ./start.sh — он впишет свежий адрес, потом /start в боте.",
        )
        return report()

    status, body = fetch(f"{public_url}/healthz")
    if status == 200:
        try:
            data = json.loads(body)
            ok(f"Сервер отвечает снаружи, бот: @{data.get('bot') or '—'}")
            if not data.get("bot"):
                note("Бот не подключён к Telegram — проверь токен и интернет")
        except ValueError:
            ok("Сервер отвечает снаружи")
    else:
        bad(
            f"Снаружи адрес не отвечает ({status or body})",
            "Домен есть, а приложение за ним не отвечает. Перезапусти ./start.sh.",
        )

    status, _ = fetch(f"{public_url}/app/")
    if status == 200:
        ok("Страница приложения открывается")
    else:
        bad(f"Страница приложения не открылась ({status})", "Перезапусти ./start.sh.")

    # 5. Что Telegram знает о боте
    if token and not token.startswith("123456:ABC-DEF"):
        status, body = fetch(f"https://api.telegram.org/bot{token}/getMe")
        if status == 200:
            data = json.loads(body).get("result", {})
            ok(f"Telegram видит бота: @{data.get('username')}")
        else:
            bad(f"Telegram не принял токен ({status})", "Проверь BOT_TOKEN в .env — возможно, скопирован не полностью.")

        status, body = fetch(f"https://api.telegram.org/bot{token}/getChatMenuButton")
        if status == 200:
            button = json.loads(body).get("result", {})
            menu_url = (button.get("web_app") or {}).get("url")
            if menu_url and not menu_url.startswith(public_url):
                bad(
                    f"Кнопка меню в BotFather ведёт на старый адрес: {menu_url}",
                    "В @BotFather: /mybots → твой бот → Bot Settings → Menu Button → "
                    f"указать {public_url}/app/ . Либо вообще убрать кнопку меню и "
                    "пользоваться клавиатурой бота — она обновляется сама.",
                )
            elif menu_url:
                ok("Кнопка меню в BotFather указывает на текущий адрес")

    return report()


def report() -> int:
    print()
    if not problems:
        print(f"{GREEN}Всё в порядке.{OFF} Если кнопка из старого сообщения не открывается — "
              "в ней зашит прежний адрес.\nОтправь боту /start и жми кнопку внизу экрана.\n")
        return 0
    print(f"{YELLOW}Что делать:{OFF}")
    for index, advice in enumerate(problems, 1):
        print(f"  {index}. {advice}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
