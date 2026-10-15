"""Navbatning kichik CI smoke testi; katta 200/5000/24h sinovi alohida CLI."""

from __future__ import annotations

from scripts.load_smoke import run


async def test_accelerated_offline_queue_keeps_all_groups_independent():
    result = await run(groups=4, ads=40, hours=3)
    assert result["type"] == "offline_sqlite_only"
    assert result["groups"] == 4 and result["ads"] == 40
    assert result["simulated_hours"] == 3 and result["post_count"] == 12
    assert result["claim_finish_p95_ms"] >= 0
