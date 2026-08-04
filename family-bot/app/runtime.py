"""Мелкое разделяемое состояние процесса (заполняется при старте бота)."""

bot_username: str | None = None


def invite_link(code: str) -> str:
    if bot_username:
        return f"https://t.me/{bot_username}?start=join_{code}"
    return f"код приглашения: {code}"
