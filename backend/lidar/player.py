"""
Odczytuje plik nagrania (format z recorder.py) i odtwarza surowe datagramy
z zachowaniem oryginalnych odstepow czasowych.
"""

import asyncio
import struct
from typing import AsyncIterator, Iterator, Tuple

_RECORD_HEADER_FMT = "<QI"
_RECORD_HEADER_LEN = struct.calcsize(_RECORD_HEADER_FMT)


def read_records(path: str) -> Iterator[Tuple[int, bytes]]:
    with open(path, "rb") as f:
        while True:
            header = f.read(_RECORD_HEADER_LEN)
            if len(header) == 0:
                return
            if len(header) < _RECORD_HEADER_LEN:
                raise EOFError("truncated recording file: incomplete record header")
            timestamp_ns, length = struct.unpack(_RECORD_HEADER_FMT, header)
            data = f.read(length)
            if len(data) < length:
                raise EOFError("truncated recording file: incomplete record payload")
            yield timestamp_ns, data


class FramePlayer:
    def __init__(self, path: str):
        self._path = path

    async def aplay(self) -> AsyncIterator[bytes]:
        prev_ts = None
        for timestamp_ns, data in read_records(self._path):
            if prev_ts is not None:
                delta_s = (timestamp_ns - prev_ts) / 1e9
                if delta_s > 0:
                    await asyncio.sleep(delta_s)
            prev_ts = timestamp_ns
            yield data
