"""Разбор быстрой траты из текста вроде «-450 бензин» или «1200 грн аптека»."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .categorizer import guess_expense_category

AMOUNT_RE = re.compile(
    r"^\s*[-–—]?\s*(?P<amount>\d[\d\s ]*(?:[.,]\d{1,2})?)\s*"
    r"(?P<currency>грн|uah|₴|usd|\$|дол|eur|€|евро|євро|pln|zł)?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)

CURRENCIES = {
    "грн": "UAH", "uah": "UAH", "₴": "UAH",
    "usd": "USD", "$": "USD", "дол": "USD",
    "eur": "EUR", "€": "EUR", "евро": "EUR", "євро": "EUR",
    "pln": "PLN", "zł": "PLN",
}

PERIOD_WORDS = {
    "monthly": ["ежемесячн", "щомісяч", "каждый месяц", "monthly", "/мес", "в месяц"],
    "quarterly": ["ежекварт", "щоквартал", "quarterly", "раз в квартал", "в квартал"],
    "yearly": ["ежегодн", "щорічн", "yearly", "раз в год", "в год", "годовая", "річна"],
}


@dataclass(slots=True)
class QuickExpense:
    amount: Decimal
    title: str
    currency: str | None
    period: str
    category_slug: str


def parse_expense(text: str) -> QuickExpense | None:
    """Возвращает разобранную трату или None, если текст на неё не похож."""
    match = AMOUNT_RE.match(text or "")
    if not match:
        return None

    raw = match.group("amount").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None

    rest = (match.group("rest") or "").strip()
    lowered = rest.lower()

    period = "once"
    for key, words in PERIOD_WORDS.items():
        if any(w in lowered for w in words):
            period = key
            break

    currency_raw = (match.group("currency") or "").lower()
    return QuickExpense(
        amount=amount,
        title=rest[:200] or "Трата",
        currency=CURRENCIES.get(currency_raw),
        period=period,
        category_slug=guess_expense_category(rest),
    )
