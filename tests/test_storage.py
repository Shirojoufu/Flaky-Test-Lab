"""Flaky: hardware failure. The disk develops a bad sector and returns EIO."""

from lab.storage import BLOCKS, BlockDevice


def test_write_and_read_back(tmp_path):
    device = BlockDevice(tmp_path / "disk.img")

    for index in range(BLOCKS):
        device.write(index, f"block {index}".encode())

    assert [device.read(i) for i in range(BLOCKS)] == [f"block {i}".encode() for i in range(BLOCKS)]
