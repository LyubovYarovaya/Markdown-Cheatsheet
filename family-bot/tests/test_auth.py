import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.auth import InvalidInitData, verify_init_data

TOKEN = "123456:TEST-TOKEN"


def make_init_data(token: str = TOKEN, auth_date: int | None = None) -> str:
    payload = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAA",
        "user": json.dumps({"id": 42, "first_name": "Люба"}, ensure_ascii=False),
    }
    check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_valid_signature():
    data = verify_init_data(make_init_data(), TOKEN)
    assert data["user"]["id"] == 42


def test_tampered_signature_rejected():
    init_data = make_init_data().replace("Aa", "Ab") + "&extra=1"
    with pytest.raises(InvalidInitData):
        verify_init_data(init_data, TOKEN)


def test_wrong_token_rejected():
    with pytest.raises(InvalidInitData):
        verify_init_data(make_init_data(), "999:OTHER")


def test_expired_rejected():
    old = int(time.time()) - 10 * 24 * 3600
    with pytest.raises(InvalidInitData):
        verify_init_data(make_init_data(auth_date=old), TOKEN)


def test_empty_rejected():
    with pytest.raises(InvalidInitData):
        verify_init_data("", TOKEN)
