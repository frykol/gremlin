"""
Nagrywa surowe datagramy UDP (dokladnie te bajty, ktore odebral
udp_listener) do pliku, z timestampem monotonicznym per rekord. Format
wlasny (nie ROS/.bag): [uint64 timestamp_ns][uint32 length][dane].
"""

import struct
import time
from typing import Optional

_RECORD_HEADER_FMT = "<QI"
_RECORD_HEADER_LEN = struct.calcsize(_RECORD_HEADER_FMT)


class FrameRecorder:
    def __init__(self, path: str):
        self._file = open(path, "wb")

    def write(self, raw_datagram: bytes, timestamp_ns: Optional[int] = None) -> None:
        timestamp_ns = timestamp_ns if timestamp_ns is not None else time.monotonic_ns()
        header = struct.pack(_RECORD_HEADER_FMT, timestamp_ns, len(raw_datagram))
        self._file.write(header)
        self._file.write(raw_datagram)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "FrameRecorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
