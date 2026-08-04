"""Разбор ссылки на товар: название, картинка, цена, магазин.

Читаем Open Graph, JSON-LD (schema.org/Product) и микроразметку — этого хватает
для большинства магазинов. Если страница закрыта или отдаёт мусор, возвращаем
хотя бы домен и очищенный URL, чтобы товар всё равно попал в список.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>()\[\]«»\"']+", re.IGNORECASE)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "yclid", "_openstat", "ref", "ref_", "sid", "mc_cid",
    "mc_eid", "igshid", "spm", "gad_source", "srsltid",
}

CURRENCY_MAP = {
    "UAH": "UAH", "ГРН": "UAH", "₴": "UAH", "USD": "USD", "$": "USD",
    "EUR": "EUR", "€": "EUR", "PLN": "PLN", "ZL": "PLN", "RUB": "RUB", "₽": "RUB",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru,uk;q=0.9,en;q=0.8",
}

MAX_BYTES = 1_500_000


@dataclass(slots=True)
class LinkPreview:
    url: str
    title: str | None = None
    image_url: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    shop: str | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        data["price"] = float(self.price) if self.price is not None else None
        return data


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;)»") for u in URL_RE.findall(text or "")]


def clean_url(url: str) -> str:
    """Убирает трекинговые хвосты, чтобы ссылки не дублировались."""
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS]
    return urlunparse(parts._replace(query=urlencode(query), fragment=""))


def shop_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_public_host(host: str) -> bool:
    """Простая защита от обращений во внутреннюю сеть."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def _to_decimal(raw) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # "1 299,00 грн" -> "1299.00"
    text = re.sub(r"[^\d,.\s]", "", text).strip()
    text = text.replace("\xa0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def _normalize_currency(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().upper()
    return CURRENCY_MAP.get(key, key[:3] if key.isalpha() else None)


def _walk_jsonld(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(str(t).lower() == "product" for t in types if t):
            out.append(node)
        for value in node.values():
            _walk_jsonld(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_jsonld(value, out)


def parse_html(html: str, url: str) -> LinkPreview:
    soup = BeautifulSoup(html, "lxml")
    preview = LinkPreview(url=url, shop=shop_name(url))

    def meta(*queries: tuple[str, str]) -> str | None:
        for attr, value in queries:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    preview.title = (
        meta(("property", "og:title"), ("name", "twitter:title"), ("itemprop", "name"))
        or (soup.title.string.strip() if soup.title and soup.title.string else None)
    )
    preview.image_url = meta(
        ("property", "og:image"), ("property", "og:image:secure_url"),
        ("name", "twitter:image"), ("itemprop", "image"),
    )
    preview.price = _to_decimal(
        meta(
            ("property", "product:price:amount"), ("property", "og:price:amount"),
            ("itemprop", "price"), ("name", "price"),
        )
    )
    preview.currency = _normalize_currency(
        meta(
            ("property", "product:price:currency"), ("property", "og:price:currency"),
            ("itemprop", "priceCurrency"),
        )
    )

    products: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            _walk_jsonld(json.loads(raw), products)
        except (ValueError, TypeError):
            continue

    for product in products:
        preview.title = preview.title or (product.get("name") or None)
        offers = product.get("offers")
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict):
            preview.price = preview.price or _to_decimal(offers.get("price"))
            preview.currency = preview.currency or _normalize_currency(offers.get("priceCurrency"))
        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, str):
            preview.image_url = preview.image_url or image
        if preview.price:
            break

    if not preview.price:
        node = soup.find(attrs={"itemprop": "price"})
        if node is not None:
            preview.price = _to_decimal(node.get("content") or node.get_text())

    if preview.title:
        preview.title = re.sub(r"\s+", " ", preview.title)[:280]
    if preview.image_url and preview.image_url.startswith("//"):
        preview.image_url = "https:" + preview.image_url

    return preview


async def fetch_preview(url: str, timeout: float = 12.0) -> LinkPreview:
    url = clean_url(url)
    host = urlparse(url).hostname or ""
    fallback = LinkPreview(url=url, shop=shop_name(url))
    if not host:
        return fallback
    if not await asyncio.to_thread(_is_public_host, host):
        return fallback

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=timeout, follow_redirects=True, max_redirects=5
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type:
                return fallback
            html = response.text[:MAX_BYTES]
            final_url = clean_url(str(response.url))
    except (httpx.HTTPError, UnicodeDecodeError):
        return fallback

    preview = parse_html(html, final_url)
    preview.shop = preview.shop or shop_name(final_url)
    return preview
