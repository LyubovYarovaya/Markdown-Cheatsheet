"""Кнопка «Открыть приложение» несёт фиксированный URL и живёт в чате вечно.

Когда адрес меняется (перезапуск временного туннеля), старые кнопки ведут в
никуда. Проверяем, что бот сам сообщает о новом адресе — но не спамит.
"""


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


async def test_first_run_is_silent_then_notifies_on_change(client):
    from app.bot.announce import STATE_KEY, announce_new_address
    from app.config import settings
    from app.db import SessionLocal
    from app.services.state import get_state

    await client.get("/api/me")  # заводим пользователя

    bot = FakeBot()
    assert await announce_new_address(bot) == 0  # первый запуск — молчим
    assert bot.sent == []

    async with SessionLocal() as session:
        assert await get_state(session, STATE_KEY) == settings.base_url

    # Тот же адрес — тоже молчим.
    assert await announce_new_address(bot) == 0
    assert bot.sent == []


async def test_new_address_reaches_every_member(client, monkeypatch):
    from app.bot.announce import announce_new_address
    from app.config import settings

    await client.get("/api/me")
    bot = FakeBot()
    await announce_new_address(bot)  # запоминаем текущий адрес

    monkeypatch.setattr(settings, "public_url", "https://new-address.trycloudflare.com")
    notified = await announce_new_address(bot)

    assert notified >= 1
    assert all("Адрес приложения обновился" in text for _, text in bot.sent)
    assert any("/share" in text for _, text in bot.sent)

    # Повторный запуск с тем же новым адресом уже молчит.
    before = len(bot.sent)
    await announce_new_address(bot)
    assert len(bot.sent) == before
