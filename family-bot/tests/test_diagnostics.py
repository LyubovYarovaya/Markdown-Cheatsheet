from app.services.diagnostics import probe


async def test_probe_reports_dead_domain():
    ok, reason = await probe("https://this-tunnel-is-long-gone.invalid/healthz")
    assert ok is False
    assert "не резолвится" in reason


async def test_probe_rejects_garbage_url():
    ok, reason = await probe("не-ссылка")
    assert ok is False
    assert reason


async def test_healthz_shape_matches_what_doctor_expects(client):
    """doctor.py читает из /healthz поля ok и bot — они не должны пропасть."""
    payload = (await client.get("/healthz")).json()
    assert payload["ok"] is True
    assert "bot" in payload
