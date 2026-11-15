from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.acquisition.rpi_w25q64 import META_HEADER, RPiW25Q64Provider


def test_fivsed_metadata_parser() -> None:
    body = b"MANUFACTURER=Lenovo\nPRODUCT=ThinkPad T14 Gen 2\nSERIAL=FIVSED-LEN-T14G2-003\nBIOS_VERSION=FIVSED-3.00\n"
    raw = META_HEADER + len(body).to_bytes(4, "little") + body + b"\xff" * 32
    meta = RPiW25Q64Provider._parse_metadata(raw)
    assert meta["MANUFACTURER"] == "Lenovo"
    assert meta["PRODUCT"] == "ThinkPad T14 Gen 2"
    assert meta["SERIAL"] == "FIVSED-LEN-T14G2-003"
    assert meta["BIOS_VERSION"] == "FIVSED-3.00"
