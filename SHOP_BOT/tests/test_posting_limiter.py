"""Phase 4: guruh/global limiter atomar rezervatsiyasi (vaqt mock, uxlamaydi)."""

from __future__ import annotations

from app.services import posting_limiter as limits


async def test_group_gap_and_album_cost(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(limits.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(limits.redis_manager, "available", False)
    limiter = limits.PostingRateLimiter()
    assert await limiter._local_reserve(-100, 10) == 0
    assert await limiter._local_reserve(-100, 1) >= 2.0  # albomdan keyin reply uchun 2s
    clock[0] += 2.0
    assert await limiter._local_reserve(-100, 10) == 0
    clock[0] += 2.0
    # Ikki albom 20 xabar sig'imini ishlatdi; 20/daq chegara kutishni talab qiladi.
    assert await limiter._local_reserve(-100, 10) > 20
    assert await limiter._local_reserve(-101, 1) == 0  # boshqa guruh ishlaydi


async def test_global_bucket_caps_bursts(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(limits.time, "monotonic", lambda: clock[0])
    limiter = limits.PostingRateLimiter()
    assert await limiter._local_reserve(-100, 20) == 0
    wait = await limiter._local_reserve(-101, 10)
    assert 0.19 <= wait <= 0.21  # 25 token sig'im, 25 msg/s tezlik
    clock[0] += 0.2
    assert await limiter._local_reserve(-101, 10) == 0


async def test_redis_reservation_waits_outside_transaction(monkeypatch) -> None:
    class Redis:
        def __init__(self):
            self.args = []
            self.times = 0

        async def eval(self, *args):
            self.args.append(args)
            self.times += 1
            return 500 if self.times == 1 else 0

    redis = Redis()
    monkeypatch.setattr(limits.redis_manager, "_client", redis)
    monkeypatch.setattr(limits.redis_manager, "available", True)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(limits.asyncio, "sleep", fake_sleep)
    await limits.PostingRateLimiter().acquire(-10055, cost=10)
    assert sleeps == [0.5]
    assert len(redis.args) == 2
    assert redis.args[0][1] == 2  # Lua 2 ta Redis kalitini atomar o'zgartiradi
    assert redis.args[0][3] == "shopbot:post:group:-10055"
    assert redis.args[0][4] == 10
