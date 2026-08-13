import datetime as dt

from dateutil.relativedelta import relativedelta

from app.models import Expense
from app.services.recurring import due_state, next_due_after


def test_next_due_after_steps_by_period():
    today = dt.date(2026, 8, 13)
    assert next_due_after(dt.date(2026, 8, 5), "monthly", today) == dt.date(2026, 9, 5)
    assert next_due_after(dt.date(2026, 8, 5), "quarterly", today) == dt.date(2026, 11, 5)
    assert next_due_after(dt.date(2026, 8, 5), "yearly", today) == dt.date(2027, 8, 5)
    assert next_due_after(dt.date(2026, 8, 5), "once", today) is None


def test_next_due_clamps_short_months():
    # 31 января + месяц = 28 февраля, а не «31 февраля».
    assert next_due_after(dt.date(2026, 1, 31), "monthly", dt.date(2026, 1, 31)) == dt.date(2026, 2, 28)


def test_next_due_skips_over_missed_periods():
    # Платёж забыли на полгода — срок должен встать в будущее, а не в прошлое.
    result = next_due_after(dt.date(2026, 1, 10), "monthly", today=dt.date(2026, 8, 13))
    assert result == dt.date(2026, 9, 10)


def test_due_state_captions():
    today = dt.date(2026, 8, 13)
    template = Expense(next_due_on=dt.date(2026, 8, 13), period="monthly", amount=1, spent_on=today)
    assert due_state(template, today) == (0, "сегодня")

    template.next_due_on = dt.date(2026, 8, 14)
    assert due_state(template, today) == (1, "завтра")

    template.next_due_on = dt.date(2026, 8, 10)
    days, caption = due_state(template, today)
    assert days == -3 and "просрочен" in caption

    template.next_due_on = None
    assert due_state(template, today) == (None, "")


async def test_template_reminder_cycle(client):
    """Шаблон с близким сроком попадает в напоминания, оплата двигает срок."""
    from app.db import SessionLocal
    from app.services.recurring import pay_template, templates_due

    today = dt.date.today()
    soon = (today + dt.timedelta(days=1)).isoformat()

    created = (await client.post("/api/expenses", json={
        "amount": 12000, "title": "Аренда квартиры", "period": "monthly",
        "is_template": True, "next_due_on": soon,
    })).json()
    assert created["next_due_on"] == soon
    assert created["due_caption"] == "завтра"

    async with SessionLocal() as session:
        due = await templates_due(session, remind_days_before=2, today=today)
        assert created["id"] in [row.id for row in due]

        # Далёкий платёж в выборку не попадает.
        far = await client.post("/api/expenses", json={
            "amount": 500, "title": "Страховка", "period": "yearly",
            "is_template": True, "next_due_on": (today + dt.timedelta(days=200)).isoformat(),
        })
        due_again = await templates_due(session, remind_days_before=2, today=today)
        assert far.json()["id"] not in [row.id for row in due_again]

    paid = (await client.post(f"/api/expenses/{created['id']}/pay", json={})).json()
    assert paid["is_template"] is False
    assert paid["amount"] == 12000

    templates = (await client.get("/api/expenses?templates=true")).json()
    template = next(row for row in templates if row["id"] == created["id"])
    # Срок уехал ровно на месяц вперёд от прежнего.
    assert template["next_due_on"] == (dt.date.fromisoformat(soon) + relativedelta(months=1)).isoformat()


async def test_reminder_pass_marks_templates_as_notified(client, monkeypatch):
    """Напоминание уходит один раз в день, даже если проход вызвать дважды."""
    from app.bot import reminders
    from app.db import SessionLocal
    from app.models import Expense as ExpenseModel

    today = dt.date.today()
    created = (await client.post("/api/expenses", json={
        "amount": 300, "title": "Интернет", "period": "monthly",
        "is_template": True, "next_due_on": today.isoformat(),
    })).json()

    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            sent.append((chat_id, text))

    count = await reminders.send_due_reminders(FakeBot(), today=today)
    assert count >= 1
    assert any("Интернет" in text for _, text in sent)

    before = len(sent)
    await reminders.send_due_reminders(FakeBot(), today=today)
    assert len(sent) == before  # второй проход в тот же день молчит

    async with SessionLocal() as session:
        template = await session.get(ExpenseModel, created["id"])
        assert template.last_reminded_on == today
