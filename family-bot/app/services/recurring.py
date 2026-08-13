"""Регулярные платежи: когда следующий, что просрочено, отметка об оплате."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Expense, User

STEP = {
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
    "yearly": relativedelta(years=1),
}


def next_due_after(current: dt.date, period: str, today: dt.date | None = None) -> dt.date | None:
    """Следующая дата платежа после текущей.

    Если платёж просрочен на несколько периодов, проматываем вперёд — иначе
    напоминания начнут отставать от календаря.
    """
    step = STEP.get(period)
    if step is None:
        return None
    today = today or dt.date.today()
    upcoming = current + step
    while upcoming <= today:
        upcoming += step
    return upcoming


def due_state(template: Expense, today: dt.date | None = None) -> tuple[int | None, str]:
    """Сколько дней до платежа и короткая подпись для человека."""
    if not template.next_due_on:
        return None, ""
    today = today or dt.date.today()
    days = (template.next_due_on - today).days
    if days < 0:
        return days, f"просрочен на {-days} дн."
    if days == 0:
        return days, "сегодня"
    if days == 1:
        return days, "завтра"
    return days, f"через {days} дн."


async def templates_due(
    session: AsyncSession, remind_days_before: int, today: dt.date | None = None
) -> list[Expense]:
    """Шаблоны, о которых пора напомнить: срок близко и сегодня ещё не писали."""
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=remind_days_before)
    rows = await session.scalars(
        select(Expense)
        .options(selectinload(Expense.category))
        .where(
            Expense.is_template.is_(True),
            Expense.next_due_on.is_not(None),
            Expense.next_due_on <= horizon,
        )
        .order_by(Expense.household_id, Expense.next_due_on)
    )
    return [row for row in rows if row.last_reminded_on is None or row.last_reminded_on < today]


async def pay_template(
    session: AsyncSession,
    template: Expense,
    user: User | None = None,
    amount: Decimal | None = None,
    spent_on: dt.date | None = None,
) -> Expense:
    """Отмечает регулярный платёж оплаченным: создаёт факт и двигает срок."""
    spent_on = spent_on or dt.date.today()
    fact = Expense(
        household_id=template.household_id,
        category_id=template.category_id,
        title=template.title,
        amount=amount if amount is not None else template.amount,
        currency=template.currency,
        period=template.period,
        spent_on=spent_on,
        note=template.note,
        is_template=False,
        created_by_id=user.id if user else template.created_by_id,
    )
    session.add(fact)

    base = template.next_due_on or spent_on
    template.next_due_on = next_due_after(base, template.period, today=spent_on)
    template.last_reminded_on = None
    await session.commit()
    await session.refresh(fact)
    return fact


async def skip_template(session: AsyncSession, template: Expense) -> Expense:
    """Пропустить платёж: срок сдвигается, трата не записывается."""
    base = template.next_due_on or dt.date.today()
    template.next_due_on = next_due_after(base, template.period)
    template.last_reminded_on = None
    await session.commit()
    return template
