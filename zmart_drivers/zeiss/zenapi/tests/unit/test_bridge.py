"""The async->blocking bridge: submit (result/exception/timeout) and stream."""

import asyncio

import pytest
from mock_zen_api import build_fake_client


@pytest.fixture
def client():
    c, _ = build_fake_client()
    yield c
    c.close()


def test_submit_returns_result(client):
    async def val():
        return 42

    assert client.submit(val()) == 42


def test_submit_reraises_exception(client):
    async def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        client.submit(boom())


def test_submit_timeout_raises_timeouterror(client):
    async def slow():
        await asyncio.sleep(2.0)

    with pytest.raises(TimeoutError):
        client.submit(slow(), timeout=0.05)


def test_stream_yields_then_stops(client):
    async def gen():
        for i in (1, 2, 3):
            yield i

    assert list(client.stream(lambda: gen())) == [1, 2, 3]


def test_stream_reraises_async_error(client):
    async def gen():
        yield 1
        raise RuntimeError("stream boom")

    seen = []
    with pytest.raises(RuntimeError, match="stream boom"):
        for x in client.stream(lambda: gen()):
            seen.append(x)
    assert seen == [1]


def test_close_is_idempotent(client):
    client.close()
    client.close()  # must not raise
