"""Block storage on a disk that can develop a bad sector."""

from __future__ import annotations

import errno
from pathlib import Path

from . import chaos

BAD_SECTOR = chaos.fires("storage.bad_sector", 0.15)
BLOCK_SIZE = 512
BLOCKS = 64


class BlockDevice:
    def __init__(self, path: Path, bad_block: int | None = None):
        self.path = path
        if bad_block is None and BAD_SECTOR:
            bad_block = chaos.rng("storage.bad_block").randrange(BLOCKS)
        self.bad_block = bad_block
        path.write_bytes(b"\0" * BLOCK_SIZE * BLOCKS)

    def write(self, index: int, data: bytes) -> None:
        self._check(index)
        with self.path.open("r+b") as disk:
            disk.seek(index * BLOCK_SIZE)
            disk.write(data.ljust(BLOCK_SIZE, b"\0"))

    def read(self, index: int) -> bytes:
        self._check(index)
        with self.path.open("rb") as disk:
            disk.seek(index * BLOCK_SIZE)
            return disk.read(BLOCK_SIZE).rstrip(b"\0")

    def _check(self, index: int) -> None:
        if index == self.bad_block:
            raise OSError(errno.EIO, "Input/output error", str(self.path))
