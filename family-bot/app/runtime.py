"""Мелкое разделяемое состояние процесса (заполняется при старте бота)."""

bot_username: str | None = None

# Идёт ли сейчас опрос Telegram. Если опрос упал (например, тот же токен
# запущен во втором окне), бот молчит на все сообщения — и это надо видеть.
polling_ok: bool = False
last_error: str | None = None


def invite_link(code: str) -> str:
    if bot_username:
        return f"https://t.me/{bot_username}?start=join_{code}"
    return f"код приглашения: {code}"
