"""
Testy ClientRegistry.broadcast - w szczegolnosci odpornosci na wolnego
klienta (head-of-line blocking).
"""

import asyncio

import pytest

from backend.lidar.ws_server import ClientRegistry


class RecordingClient:
    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.received = []

    async def send(self, message):
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.received.append(message)


class FailingClient:
    def __init__(self, exc=None):
        self.exc = exc or ConnectionResetError("polaczenie zerwane")

    async def send(self, message):
        raise self.exc


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_clients():
    reg = ClientRegistry()
    a, b = RecordingClient(), RecordingClient()
    reg.add(a)
    reg.add(b)

    await reg.broadcast(b"frame")
    await reg.drain()

    assert a.received == [b"frame"]
    assert b.received == [b"frame"]


@pytest.mark.asyncio
async def test_failing_client_is_removed_and_others_keep_receiving():
    reg = ClientRegistry()
    good, bad = RecordingClient(), FailingClient()
    reg.add(good)
    reg.add(bad)

    await reg.broadcast(b"first")
    await reg.drain()
    await reg.broadcast(b"second")
    await reg.drain()

    assert good.received == [b"first", b"second"]
    assert reg.client_count == 1  # zerwany klient usuniety


@pytest.mark.asyncio
async def test_slow_client_does_not_stall_the_pipeline():
    # Regresja: broadcast wysylal sekwencyjnie z `await`, wiec JEDEN wolny
    # klient (slabe wifi, pelny bufor TCP) zatrzymywal cala petle - zmierzone
    # 20Hz -> 2Hz dla WSZYSTKICH, lacznie z lokalna przegladarka i pętlą
    # detekcji przeszkod. Strumien chmury punktow jest live: pominiecie
    # ramki dla klienta, ktory nie nadaza, jest poprawne; czekanie na niego
    # nie jest.
    reg = ClientRegistry()
    slow = RecordingClient(delay_s=0.5)
    fast = RecordingClient()
    reg.add(slow)
    reg.add(fast)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for i in range(4):
        await reg.broadcast(f"frame{i}".encode())
    elapsed = loop.time() - t0

    # Cztery ramki nie moga zajac ~2s (4 x 0.5s) tylko dlatego, ze jeden
    # klient jest wolny - broadcast() wklada do kolejek i wraca od razu.
    assert elapsed < 0.1, f"broadcast zablokowany przez wolnego klienta: {elapsed:.2f}s"

    # Szybki klient dostaje swoje ramki od razu, mimo ze wolny wciaz wisi
    # na pierwszej (to jest sedno poprawki: kanaly sa niezalezne).
    await asyncio.sleep(0.05)
    assert len(fast.received) == 4
    assert len(slow.received) == 0  # wciaz w trakcie pierwszej wysylki

    await reg.close()


@pytest.mark.asyncio
async def test_slow_client_gets_frames_dropped_not_queued():
    # Dla wolnego klienta ramki sa POMIJANE (latest-wins), a nie kolejkowane -
    # inaczej kolejka rosnie w nieskonczonosc, a klient oglada coraz
    # starszy obraz.
    reg = ClientRegistry()
    slow = RecordingClient(delay_s=0.05)
    reg.add(slow)

    for i in range(10):
        await reg.broadcast(f"frame{i}".encode())
    await reg.drain()

    # Pierwsza ramka poszla, reszta zostala pominieta, bo poprzednia wysylka
    # wciaz trwala. Na pewno NIE wszystkie 10.
    assert 0 < len(slow.received) < 10
    assert reg.dropped_frames > 0


@pytest.mark.asyncio
async def test_removed_client_receives_nothing_further():
    reg = ClientRegistry()
    client = RecordingClient()
    reg.add(client)

    await reg.broadcast(b"before")
    await reg.drain()
    reg.remove(client)
    await reg.broadcast(b"after")
    await reg.drain()

    assert client.received == [b"before"]


@pytest.mark.asyncio
async def test_broadcast_with_no_clients_is_a_noop():
    reg = ClientRegistry()
    await reg.broadcast(b"nobody listening")
    await reg.drain()
    assert reg.client_count == 0
