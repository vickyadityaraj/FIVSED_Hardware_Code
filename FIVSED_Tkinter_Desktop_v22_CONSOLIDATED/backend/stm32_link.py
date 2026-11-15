from __future__ import annotations

import json
import os
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from .config import config

SYNC = 0xF5
VERSION = 1
HEADER = struct.Struct("<BBB I H H")  # type, flags, reserved, request_id, sequence, payload_len
MAX_PAYLOAD = 1024

HELLO_REQ = 0x01
HELLO_RESP = 0x81
HEARTBEAT_RESP = 0x83
PI_HEARTBEAT = 0x05
STATUS_REQ = 0x02
STATUS_RESP = 0x82
SELECT_SLOT = 0x03
SCAN_REQ = 0x04
STREAM_START = 0x10
STREAM_DATA = 0x11
STREAM_END = 0x12
STREAM_ACK = 0x13
SCAN_PROGRESS = 0x85
SCAN_RESULT = 0x86
ACK = 0x06
NACK = 0x07
ERROR = 0xE0

STREAM_DATA_OVERHEAD = 0
MAX_STREAM_BYTES = 16 * 1024 * 1024


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def encode_frame(msg_type: int, request_id: int, payload: bytes = b"", sequence: int = 0, flags: int = 0) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    header = HEADER.pack(msg_type, flags, 0, request_id & 0xFFFFFFFF, sequence & 0xFFFF, len(payload))
    crc = crc16_ccitt(bytes([VERSION]) + header + payload)
    return bytes([SYNC, VERSION]) + header + payload + struct.pack("<H", crc)


class STM32ProtocolError(RuntimeError):
    pass


@dataclass
class STM32Connection:
    port: str
    baud: int
    product: str = "STM32 FIVSED Safety Core"


class STM32Link:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._conn: Optional[STM32Connection] = None
        self._serial = None
        self._request_id = 0
        self.last_error = ""
        self.last_seen = 0.0
        self.esp32_active = False
        self.esp32_last_seen = 0.0
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="fivsed-pi-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    @property
    def connected(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    @property
    def port(self) -> str:
        return self._conn.port if self._conn else "N/A"

    def _next_request_id(self) -> int:
        self._request_id = (self._request_id + 1) & 0xFFFFFFFF
        if self._request_id == 0:
            self._request_id = 1
        return self._request_id

    def close(self) -> None:
        with self._lock:
            try:
                if self._serial is not None:
                    self._serial.close()
            except Exception:
                pass
            self._serial = None
            self._conn = None

    def _heartbeat_loop(self) -> None:
        """Tell STM32 that the Raspberry Pi application is alive.

        This is deliberately a small framed protocol message, not a security
        command. The STM32 uses its receipt only to report Pi liveness to the
        one-way ESP32 controller heartbeat.
        """
        while True:
            time.sleep(5.0)
            try:
                self._send_pi_heartbeat()
            except Exception:
                # Liveness must never crash the GUI/backend process.
                pass

    def _send_pi_heartbeat(self) -> bool:
        if not self.connected:
            return False
        # Never contend with an in-progress scan/stream. The next heartbeat
        # after the scan will refresh Pi liveness.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if not self.connected:
                return False
            rid = self._next_request_id()
            self._serial.write(encode_frame(PI_HEARTBEAT, rid, b"{\"component\":\"RaspberryPi\",\"status\":\"ACTIVE\"}"))
            self._serial.flush()
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                frame = self._read_frame_from(self._serial, min(0.25, max(0.05, deadline - time.monotonic())))
                if not frame:
                    continue
                f_type, _flags, f_req, _seq, f_payload = frame
                if f_req != rid:
                    continue
                if f_type == HEARTBEAT_RESP:
                    detail = self._decode_payload(f_payload)
                    self.esp32_active = bool(detail.get("esp32_active", False))
                    if self.esp32_active:
                        self.esp32_last_seen = time.time()
                    self.last_seen = time.time()
                    self.last_error = ""
                    return True
                if f_type == ERROR:
                    self.last_error = self._decode_payload(f_payload).get("error", "STM32 heartbeat error")
                    return False
            self.last_error = "STM32 heartbeat timeout"
            return False
        except Exception as exc:
            self.last_error = str(exc) or "STM32 heartbeat failed"
            return False
        finally:
            self._lock.release()

    @staticmethod
    def _port_is_stm32_usb(port_info) -> bool:
        vid = getattr(port_info, "vid", None)
        pid = getattr(port_info, "pid", None)
        text = " ".join(str(getattr(port_info, k, "") or "") for k in ("description", "manufacturer", "product", "hwid")).lower()
        return (vid == 0x0483 and pid == 0x5740) or ("fivsed security core" in text) or ("stm32" in text and ("cdc" in text or "virtual com" in text))

    def _candidate_ports(self) -> list[str]:
        configured = config.serial.stm32_port.strip()
        if configured:
            return [configured]
        candidates: list[str] = []
        if serial is None:
            return candidates
        try:
            ports = list(serial.tools.list_ports.comports())
            usb_stm32 = [p.device for p in ports if self._port_is_stm32_usb(p)]
            usb_other = [p.device for p in ports if p.device not in usb_stm32 and (p.device.startswith("/dev/ttyACM") or p.device.startswith("/dev/ttyUSB") or p.device.upper().startswith("COM"))]
            candidates.extend(usb_stm32)
            candidates.extend(usb_other)
        except Exception:
            pass
        if os.name != "nt":
            for path in ("/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0"):
                if os.path.exists(path) and path not in candidates:
                    candidates.append(path)
        return list(dict.fromkeys(candidates))

    def _open_and_probe(self, port: str, timeout: float = 0.8) -> bool:
        if serial is None:
            self.last_error = "pyserial is not installed"
            return False
        try:
            ser = serial.Serial(
                port=port,
                baudrate=config.serial.stm32_baud,
                timeout=0.05,
                write_timeout=0.75,
            )
            try:
                ser.dtr = True
            except Exception:
                pass
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            rid = self._next_request_id()
            ser.write(encode_frame(HELLO_REQ, rid, b"FIVSED"))
            ser.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                frame = self._read_frame_from(ser, 0.08)
                if frame and frame[0] == HELLO_RESP and frame[2] == rid:
                    self._serial = ser
                    self._conn = STM32Connection(port, config.serial.stm32_baud)
                    self.last_seen = time.time()
                    self.last_error = ""
                    return True
            ser.close()
            self.last_error = f"{port}: no STM32 FIVSED HELLO response"
        except Exception as exc:
            self.last_error = f"{port}: {exc}"
        return False

    def ensure_connected(self) -> bool:
        with self._lock:
            if self.connected:
                return True
            self.close()
            for port in self._candidate_ports():
                if self._open_and_probe(port):
                    return True
            return False

    def _read_exact(self, ser, size: int, deadline: float) -> Optional[bytes]:
        data = bytearray()
        while len(data) < size and time.monotonic() < deadline:
            chunk = ser.read(size - len(data))
            if chunk:
                data.extend(chunk)
        return bytes(data) if len(data) == size else None

    def _read_frame_from(self, ser, timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            first = ser.read(1)
            if not first:
                continue
            if first[0] != SYNC:
                continue
            version_b = self._read_exact(ser, 1, deadline)
            if not version_b:
                return None
            version = version_b[0]
            if version != VERSION:
                continue
            raw_header = self._read_exact(ser, HEADER.size, deadline)
            if not raw_header:
                return None
            msg_type, flags, _reserved, request_id, sequence, payload_len = HEADER.unpack(raw_header)
            if payload_len > MAX_PAYLOAD:
                raise STM32ProtocolError(f"invalid payload length {payload_len}")
            payload = self._read_exact(ser, payload_len, deadline)
            crc_b = self._read_exact(ser, 2, deadline)
            if payload is None or crc_b is None:
                return None
            expected = struct.unpack("<H", crc_b)[0]
            actual = crc16_ccitt(bytes([version]) + raw_header + payload)
            if actual != expected:
                raise STM32ProtocolError("CRC16 mismatch")
            self.last_seen = time.time()
            return msg_type, flags, request_id, sequence, payload
        return None

    @staticmethod
    def _decode_payload(payload: bytes) -> dict:
        if not payload:
            return {}
        try:
            value = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise STM32ProtocolError(f"invalid STM32 JSON response: {exc}") from exc
        return value if isinstance(value, dict) else {"value": value}

    def _request(
        self,
        msg_type: int,
        payload: dict | list | str | bytes,
        expected: set[int],
        timeout: float = 5.0,
        callback: Optional[Callable[[int, dict], None]] = None,
        retries: int = 0,
    ):
        if isinstance(payload, bytes):
            body = payload
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with self._lock:
            rid = self._next_request_id()
            attempts = max(0, min(2, int(retries))) + 1
            last_error = "STM32 response timeout"
            for attempt in range(attempts):
                if not self.ensure_connected():
                    raise STM32ProtocolError(self.last_error or "STM32 not connected")
                try:
                    self._serial.write(encode_frame(msg_type, rid, body))
                    self._serial.flush()
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        remaining = max(0.05, min(0.75, deadline - time.monotonic()))
                        frame = self._read_frame_from(self._serial, remaining)
                        if not frame:
                            continue
                        f_type, _flags, f_req, seq, f_payload = frame
                        if f_req != rid:
                            continue
                        if callback is not None and f_type == SCAN_PROGRESS:
                            callback(seq, self._decode_payload(f_payload))
                            continue
                        if f_type == ACK:
                            if ACK in expected:
                                return self._decode_payload(f_payload)
                            continue
                        if f_type == NACK:
                            detail = self._decode_payload(f_payload)
                            raise STM32ProtocolError(detail.get("error", "STM32 rejected request"))
                        if f_type not in expected:
                            if f_type == ERROR:
                                detail = self._decode_payload(f_payload)
                                raise STM32ProtocolError(detail.get("error", "STM32 error"))
                            continue
                        self.last_seen = time.time()
                        return self._decode_payload(f_payload)
                except STM32ProtocolError:
                    raise
                except Exception as exc:
                    last_error = str(exc) or last_error
                    self.close()
                    if attempt + 1 >= attempts:
                        raise STM32ProtocolError(last_error) from exc
            raise STM32ProtocolError(last_error)

    def _send_stream_frame_wait_ack(self, request_id: int, sequence: int, msg_type: int, payload: bytes, timeout: float = 3.0) -> dict:
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("stream payload too large")
        frame = encode_frame(msg_type, request_id, payload, sequence=sequence)
        last_error = "STM32 stream ACK timeout"
        for _attempt in range(3):
            try:
                self._serial.write(frame)
                self._serial.flush()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    incoming = self._read_frame_from(self._serial, min(0.5, max(0.05, deadline - time.monotonic())))
                    if not incoming:
                        continue
                    f_type, _flags, f_req, f_seq, f_payload = incoming
                    if f_req != request_id:
                        continue
                    if f_type == STREAM_ACK and f_seq == sequence:
                        return self._decode_payload(f_payload)
                    if f_type == NACK:
                        detail = self._decode_payload(f_payload)
                        raise STM32ProtocolError(detail.get("error", "STM32 rejected stream frame"))
                    if f_type == ERROR:
                        detail = self._decode_payload(f_payload)
                        raise STM32ProtocolError(detail.get("error", "STM32 stream error"))
                last_error = "STM32 stream ACK timeout"
            except STM32ProtocolError:
                raise
            except Exception as exc:
                last_error = str(exc) or last_error
                self.close()
                raise STM32ProtocolError(last_error) from exc
        raise STM32ProtocolError(last_error)

    def _wait_result(self, request_id: int, timeout: float, callback: Optional[Callable[[int, dict], None]] = None) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._read_frame_from(self._serial, min(0.75, max(0.05, deadline - time.monotonic())))
            if not frame:
                continue
            f_type, _flags, f_req, seq, f_payload = frame
            if f_req != request_id:
                continue
            if callback is not None and f_type == SCAN_PROGRESS:
                callback(seq, self._decode_payload(f_payload))
                continue
            if f_type == NACK:
                detail = self._decode_payload(f_payload)
                raise STM32ProtocolError(detail.get("error", "STM32 rejected scan"))
            if f_type == ERROR:
                detail = self._decode_payload(f_payload)
                raise STM32ProtocolError(detail.get("error", "STM32 scan error"))
            if f_type == SCAN_RESULT:
                return self._decode_payload(f_payload)
        raise STM32ProtocolError("STM32 verification result timeout")

    def hello(self) -> dict:
        return self._request(HELLO_REQ, {"client": "FIVSED_PI", "protocol": VERSION}, {HELLO_RESP}, timeout=1.5, retries=2)

    def status(self) -> dict:
        return self._request(STATUS_REQ, {}, {STATUS_RESP}, timeout=2.0, retries=2)

    def select_slot(self, slot: int) -> dict:
        if not 0 <= slot <= 3:
            raise ValueError("invalid slot")
        return self._request(SELECT_SLOT, {"slot": slot}, {ACK}, timeout=1.5, retries=2)

    def scan_slot(self, slot: int, callback: Optional[Callable[[int, dict], None]] = None) -> dict:
        if not 0 <= slot <= 3:
            raise ValueError("invalid slot")
        # Keep the STM32 physical/provisioning selector synchronized with the
        # target selected by the Raspberry Pi before starting a scan.
        self.select_slot(slot)
        return self._request(SCAN_REQ, {"slot": slot}, {SCAN_RESULT}, timeout=120.0, callback=callback, retries=0)

    def stream_file(
        self,
        path: str | Path,
        slot: int,
        target_id: str,
        physical_id: str = "",
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """Stream an acquired firmware image into STM32 for hashing/verification.

        ``target_id`` is the operator-facing logical target identity. ``physical_id`` is the
        real W25Q64 factory UID. Neither value is a trusted reference; the STM32 keeps the
        trusted reference digest internally and makes the final integrity decision.
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise STM32ProtocolError(f"firmware image not found: {file_path}")
        total = file_path.stat().st_size
        max_allowed = min(MAX_STREAM_BYTES, config.acquisition.max_firmware_bytes)
        if total <= 0:
            raise STM32ProtocolError("firmware image is empty")
        if total > max_allowed:
            raise STM32ProtocolError(f"firmware image exceeds configured limit ({max_allowed} bytes)")
        if not 0 <= int(slot) <= 3:
            raise STM32ProtocolError("invalid STM32 target slot")
        if not target_id or len(target_id) > 31:
            raise STM32ProtocolError("target_id must contain 1..31 characters")
        if not self.ensure_connected():
            raise STM32ProtocolError(self.last_error or "STM32 not connected")

        with self._lock:
            if not self.connected:
                raise STM32ProtocolError("STM32 serial connection closed before streaming")
            # This selection is security-relevant because the STM32 physical
            # REGISTER/RE-BASELINE actions apply to the active slot only.
            self.select_slot(int(slot))
            rid = self._next_request_id()
            chunk_size = max(256, min(MAX_PAYLOAD, config.acquisition.stream_chunk_bytes))
            start_obj = {
                "slot": int(slot),
                "target_id": str(target_id),
                "total_bytes": int(total),
                "source": "FIVSED_ACQUISITION",
            }
            if physical_id:
                start_obj["physical_id"] = str(physical_id)[:31]
            start_payload = json.dumps(start_obj, separators=(",", ":")).encode("utf-8")
            if progress:
                progress(0, int(total), "ACQUIRING_FIRMWARE")
            self._send_stream_frame_wait_ack(rid, 0, STREAM_START, start_payload, timeout=3.0)
            processed = 0
            sequence = 0
            with file_path.open("rb") as src:
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    ack = self._send_stream_frame_wait_ack(rid, sequence, STREAM_DATA, chunk, timeout=3.0)
                    processed += len(chunk)
                    sequence = (sequence + 1) & 0xFFFF
                    ack_done = int(ack.get("bytes_processed", processed) or processed)
                    if progress:
                        progress(min(processed, total), total, "STREAMING_TO_STM32")
                    if ack_done != processed:
                        raise STM32ProtocolError(f"STM32 stream progress mismatch: expected {processed}, got {ack_done}")
            self._send_stream_frame_wait_ack(rid, sequence, STREAM_END, b"", timeout=3.0)
            if progress:
                progress(int(total), int(total), "VERIFYING_REFERENCE")
            return self._wait_result(rid, timeout=max(120.0, total / 8192.0), callback=None)

    def component_status(self) -> dict:
        connected = self.connected or self.ensure_connected()
        transport = "USB_CDC" if self.port.startswith("/dev/ttyACM") or self.port.upper().startswith("COM") else "UART"
        return {
            "connected": connected,
            "port": self.port,
            "transport": transport,
            "last_seen": self.last_seen or None,
            "error": self.last_error or None,
            "esp32_active": bool(self.esp32_active),
            "esp32_last_seen": self.esp32_last_seen or None,
            "esp32_transport": "STM32_UART_HEARTBEAT",
        }


stm32_link = STM32Link()
