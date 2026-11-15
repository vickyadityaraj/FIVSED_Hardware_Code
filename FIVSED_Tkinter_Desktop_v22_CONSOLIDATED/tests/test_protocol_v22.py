from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.stm32_link import crc16_ccitt, encode_frame, HEADER, SYNC, VERSION, PI_HEARTBEAT
import struct


def test_crc_known_vector() -> None:
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_pi_heartbeat_frame_layout() -> None:
    payload = b'{"component":"RaspberryPi","status":"ACTIVE"}'
    frame = encode_frame(PI_HEARTBEAT, 0x12345678, payload, sequence=7)
    assert frame[0:2] == bytes([SYNC, VERSION])
    raw_header = frame[2:2 + HEADER.size]
    msg_type, flags, reserved, request_id, sequence, length = HEADER.unpack(raw_header)
    assert msg_type == PI_HEARTBEAT
    assert flags == 0
    assert reserved == 0
    assert request_id == 0x12345678
    assert sequence == 7
    assert length == len(payload)
    expected = struct.unpack_from("<H", frame, 2 + HEADER.size + length)[0]
    actual = crc16_ccitt(bytes([VERSION]) + raw_header + payload)
    assert expected == actual
