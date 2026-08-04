from decimal import Decimal

from app.services.categorizer import guess_category, guess_expense_category
from app.services.link_parser import clean_url, extract_urls, parse_html
from app.services.quick_expense import parse_expense


def test_category_by_title():
    assert guess_category("Коляска 2 в 1 Anex", "https://shop.ua/p/123").slug == "baby"
    assert guess_category("Ноутбук ASUS Vivobook 15").slug == "tech"
    assert guess_category("Сковорода Tefal 28 см").slug == "kitchen"
    assert guess_category("Комплект постельного белья сатин").slug == "textile"
    assert guess_category("Настольная лампа для спальни").slug == "home"


def test_category_by_url_when_title_is_useless():
    guess = guess_category("Товар", "https://rozetka.com.ua/detskie-kolyaski/c80253/")
    assert guess.slug == "baby"


def test_unknown_category_is_not_confident():
    guess = guess_category("Какая-то штука")
    assert guess.slug == "other"
    assert not guess.confident


def test_expense_categories():
    assert guess_expense_category("бензин на трассе") == "car"
    assert guess_expense_category("аптека витамины") == "health"
    assert guess_expense_category("netflix подписка") == "subscriptions"


def test_extract_and_clean_urls():
    text = "смотри https://shop.ua/item?utm_source=tg&id=5 вот такое"
    urls = extract_urls(text)
    assert urls == ["https://shop.ua/item?utm_source=tg&id=5"]
    assert clean_url(urls[0]) == "https://shop.ua/item?id=5"


def test_parse_html_reads_open_graph():
    html = """
    <html><head>
      <meta property="og:title" content="Робот-пылесос Dreame L10">
      <meta property="og:image" content="//cdn.shop/img.jpg">
      <meta property="product:price:amount" content="12 499,00">
      <meta property="product:price:currency" content="UAH">
    </head><body></body></html>
    """
    preview = parse_html(html, "https://shop.ua/p/1")
    assert preview.title == "Робот-пылесос Dreame L10"
    assert preview.image_url == "https://cdn.shop/img.jpg"
    assert preview.price == Decimal("12499.00")
    assert preview.currency == "UAH"
    assert preview.shop == "shop.ua"


def test_parse_html_reads_json_ld():
    html = """
    <html><head><script type="application/ld+json">
      {"@type": "Product", "name": "Кроватка Ikea",
       "offers": {"@type": "Offer", "price": "3499.50", "priceCurrency": "UAH"}}
    </script></head><body></body></html>
    """
    preview = parse_html(html, "https://ikea.ua/p/2")
    assert preview.title == "Кроватка Ikea"
    assert preview.price == Decimal("3499.50")


def test_quick_expense():
    parsed = parse_expense("450 бензин")
    assert parsed.amount == Decimal("450")
    assert parsed.category_slug == "car"
    assert parsed.period == "once"

    parsed = parse_expense("1 200,50 грн аптека ежемесячная")
    assert parsed.amount == Decimal("1200.50")
    assert parsed.currency == "UAH"
    assert parsed.period == "monthly"
    assert parsed.category_slug == "health"

    parsed = parse_expense("90 usd страховка машины ежегодная")
    assert parsed.currency == "USD"
    assert parsed.period == "yearly"

    assert parse_expense("просто текст") is None
