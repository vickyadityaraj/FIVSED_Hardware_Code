# FIVSED v22 web application integration

The ESP32 sends web events to the configured endpoint (for example `POST /api/events`). The web application should authenticate the gateway using the configured API key and device ID.

## STM32 verification event

The ESP32 must forward the exact STM32 JSON body without editing it because the STM32 HMAC covers the JSON bytes.

Headers:

```text
Content-Type: application/json
X-FIVSED-Device-ID: <configured device id>
X-FIVSED-API-Key: <configured API key>
X-FIVSED-STM32-HMAC: <lowercase hex HMAC-SHA256>
```

Example body fields:

```json
{
  "version": 1,
  "event": "FIRMWARE_VERIFICATION",
  "source": "STM32",
  "decision_authority": "STM32",
  "verification_id": 101,
  "scan_id": 101,
  "slot": 0,
  "result": "HASH_MISMATCH",
  "status": "FAIL",
  "firmware_size": 8388608,
  "duration_ms": 4200,
  "reason": "Firmware measurement differs from STM32 trusted reference",
  "hash_disclosure": false
}
```

The server should use the authenticated device ID header to associate the event with the FIVSED unit. It should not require the ESP32 to inject a device ID into an STM32-signed body.

## Component heartbeat

The ESP32 creates its own local heartbeat every 15 seconds. Example:

```json
{
  "version": 1,
  "event": "COMPONENT_HEARTBEAT",
  "device_id": "FIVSED-001",
  "source": "ESP32_GATEWAY",
  "status": "ACTIVE",
  "esp32_active": true,
  "stm32_active": true,
  "raspberry_pi_active": true,
  "esp32_uptime_ms": 45000
}
```

The dashboard can compute `ONLINE` from the most recent heartbeat, using a lease such as 45 seconds. The individual component flags are informational liveness values; the firmware-integrity result remains the STM32 decision.

## Result mapping

- `MATCH`, `NEW_TARGET_REGISTERED`, `REFERENCE_UPDATED` -> `PASS`
- `HASH_MISMATCH` -> `FAIL` / security alert
- `READ_ERROR` -> `FAIL` or operational error according to the dashboard's schema
- `FIRMWARE_READ_UNSUPPORTED` / `FIRMWARE_ACCESS_PROTECTED` -> acquisition-status event rather than an integrity match

The dashboard should use factual wording such as "Firmware integrity verification failed because the measured data did not match the trusted reference" and should not claim who modified the firmware or why.
