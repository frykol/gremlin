"""
Parser ramek UDP z bridge'a - jedyne miejsce w pipeline, ktore przyjmuje
surowe bajty z sieci. handle_datagram() w app.py lapie WYLACZNIE
FrameParseError, wiec kazdy inny wyjatek (IndexError, struct.error nie
opakowany, itp.) na uszkodzonym/zlosliwym datagramie ubilby cala petle
odbioru UDP w produkcji. Ten plik pilnuje wlasnosci "cokolwiek przyjdzie
z sieci, parser albo zwraca wynik, albo rzuca WYLACZNIE FrameParseError".
"""

import random
import struct

import pytest

from backend.lidar.frame_parser import (
    FrameParseError,
    ImuFrame,
    ScanFrame,
    parse_udp_datagram,
)


def test_empty_datagram_raises_parse_error():
    with pytest.raises(FrameParseError):
        parse_udp_datagram(b"")


def test_header_only_no_payload_is_fine_for_unknown_type():
    # msgType nieznany + length=0 -> brak payloadu do sparsowania, None.
    data = struct.pack("<II", 999, 0)
    assert parse_udp_datagram(data) is None


def test_unknown_msg_type_with_payload_returns_none():
    data = struct.pack("<II", 999, 10) + bytes(10)
    assert parse_udp_datagram(data) is None


def test_declared_length_exceeding_actual_payload_raises():
    # Naglowek klamie o dlugosci wiekszej niz faktycznie dostarczone bajty.
    data = struct.pack("<II", 102, 5000) + bytes(10)
    with pytest.raises(FrameParseError):
        parse_udp_datagram(data)


def test_scan_with_valid_points_num_exceeding_max_raises():
    body = struct.pack("<dII", 1.0, 1, 999) + bytes(120 * 24)
    data = struct.pack("<II", 102, len(body)) + body
    with pytest.raises(FrameParseError):
        parse_udp_datagram(data)


def test_scan_truncated_mid_point_raises():
    # validPointsNum mowi 10 punktow, ale payload ma miejsce tylko na 2.
    prefix = struct.pack("<dII", 1.0, 1, 10)
    body = prefix + bytes(24 * 2)
    data = struct.pack("<II", 102, len(body)) + body
    with pytest.raises(FrameParseError):
        parse_udp_datagram(data)


def test_imu_truncated_raises():
    data = struct.pack("<II", 101, 5) + bytes(5)
    with pytest.raises(FrameParseError):
        parse_udp_datagram(data)


def test_well_formed_scan_roundtrips():
    # Bridge zawsze wysyla pelna stala tablice 120 punktow (patrz
    # POINTS_PER_SCAN) - validPointsNum mowi ile z nich jest znaczacych,
    # ale payload musi miec miejsce na wszystkie 120.
    n = 3
    prefix = struct.pack("<dII", 1.5, 42, n)
    real_points = b"".join(
        struct.pack("<fffffI", float(i), float(i), 0.0, 100.0, 0.0, 0) for i in range(n)
    )
    padding = bytes(24 * (120 - n))
    data = struct.pack("<II", 102, len(prefix + real_points + padding)) + prefix + real_points + padding

    frame = parse_udp_datagram(data)

    assert isinstance(frame, ScanFrame)
    assert frame.id == 42
    assert len(frame.points) == n


def test_well_formed_imu_roundtrips():
    body = struct.pack("<dI4f3f3f", 2.5, 7, *([0.0] * 10))
    data = struct.pack("<II", 101, len(body)) + body

    frame = parse_udp_datagram(data)

    assert isinstance(frame, ImuFrame)
    assert frame.id == 7


def test_fuzz_random_bytes_never_raise_anything_but_frame_parse_error():
    """
    Regresja przez konstrukcje: rzuca dowolna liczbe losowych/uszkodzonych
    datagramow (naglowki z realnymi typami msgType, uciete body, smieciowe
    dlugosci) i wymaga, ze KAZDY wynik to albo poprawny zwrot, albo
    FrameParseError - nigdy nic innego.
    """
    rng = random.Random(1234)
    for _ in range(5000):
        mode = rng.randrange(4)
        if mode == 0:
            data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        elif mode == 1:
            data = struct.pack(
                "<II", rng.choice([101, 102, 0, 999]), rng.randrange(0, 2**32 - 1)
            ) + bytes(rng.randrange(256) for _ in range(rng.randrange(0, 80)))
        elif mode == 2:
            data = struct.pack("<II", 102, rng.randrange(0, 5000)) + bytes(
                rng.randrange(256) for _ in range(rng.randrange(0, 3000))
            )
        else:
            body = struct.pack("<dII", 1.0, 1, rng.randrange(0, 300)) + bytes(2880)
            data = struct.pack("<II", 102, len(body)) + body

        try:
            parse_udp_datagram(data)
        except FrameParseError:
            pass
        except Exception as exc:  # pragma: no cover - to jest wlasnie usterka, ktora lapiemy
            pytest.fail(
                f"parse_udp_datagram rzucil {type(exc).__name__} zamiast "
                f"FrameParseError na wejsciu {data!r}"
            )
