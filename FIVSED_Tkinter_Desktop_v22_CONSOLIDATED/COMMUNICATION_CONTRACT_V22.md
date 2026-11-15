# FIVSED v22 Communication Contract

## Trust model

```text
W25Q64 -> Raspberry Pi -> STM32F411CEU6 <-> ESP32 -> HTTPS -> Web application
```

- Raspberry Pi: acquisition, operator GUI, and liveness heartbeat only.
- STM32F411CEU6: sole integrity authority; computes SHA-256, stores trusted references, compares, and classifies results.
- ESP32: Wi-Fi/HTTPS telemetry, status/actuator gateway; it never computes or stores the trusted firmware reference.
- Web application: stores and displays signed/identified events; it never becomes the integrity authority.

## Pi <-> STM32 USB CDC frame

```text
F5 | VERSION=01 | TYPE | FLAGS | RESERVED | REQUEST_ID(u32 LE) | SEQUENCE(u16 LE) | LENGTH(u16 LE) | PAYLOAD | CRC16(u16 LE)
```

CRC16-CCITT is calculated over `VERSION + TYPE..LENGTH + PAYLOAD` (the sync byte is excluded).

The currently used message types are:

- `01` HELLO_REQ / `81` HELLO_RESP
- `02` STATUS_REQ / `82` STATUS_RESP
- `03` SELECT_SLOT / `06` ACK / `07` NACK
- `04` SCAN_REQ / `86` SCAN_RESULT
- `05` PI_HEARTBEAT / `83` HEARTBEAT_RESP
- `10` STREAM_START
- `11` STREAM_DATA
- `12` STREAM_END
- `13` STREAM_ACK
- `85` SCAN_PROGRESS
- `E0` ERROR

## ESP32 -> STM32 heartbeat frame

```text
5A | VERSION=01 | LENGTH(u16 LE) | JSON PAYLOAD | CRC16(u16 LE)
```

The CRC is calculated over `VERSION + LENGTH + JSON PAYLOAD`.

Heartbeat JSON:

```json
{"version":1,"event":"ESP32_HEARTBEAT","source":"ESP32","status":"ACTIVE","sequence":1,"esp32_uptime_ms":1234}
```

Only the `ESP32_HEARTBEAT` event is accepted on this reverse-control channel. A valid heartbeat causes STM32 to update the ESP32 liveness timestamp and send an authenticated ACK.

## STM32 -> ESP32 authenticated event frame

```text
A5 | LENGTH(u16 LE) | JSON PAYLOAD | HMAC-SHA256(32 bytes)
```

The HMAC covers the JSON payload only. The secret key never leaves STM32.

Heartbeat ACK JSON:

```json
{"version":1,"event":"ESP32_HEARTBEAT_ACK","source":"STM32","status":"ACK","message":"ACK: ESP32_ACTIVE","stm32_active":true,"sequence":2}
```

Component heartbeat JSON:

```json
{"version":1,"event":"COMPONENT_HEARTBEAT","source":"STM32","status":"ACTIVE","stm32_active":true,"raspberry_pi_active":true,"esp32_active":true,"stm32_uptime_ms":1234,"pi_last_seen_ms":900,"esp32_last_seen_ms":850,"sequence":3}
```

Firmware verification JSON:

```json
{"version":1,"event":"FIRMWARE_VERIFICATION","source":"STM32","decision_authority":"STM32","verification_id":123,"scan_id":123,"slot":0,"result":"MATCH","status":"PASS","firmware_size":8388608,"duration_ms":4200,"reason":"Firmware measurement matches STM32 trusted reference","hash_disclosure":false}
```

The raw SHA-256 digest and trusted reference are never included in this payload.

## Liveness timing

- ESP32 heartbeat to STM32: every 5 seconds.
- STM32 considers ESP32 active for 15 seconds after a valid heartbeat.
- STM32 -> ESP32 component heartbeat: every 5 seconds.
- Raspberry Pi heartbeat to STM32: every 5 seconds.
- STM32 considers Pi active for 45 seconds after a valid heartbeat.
- ESP32 web gateway heartbeat: every 15 seconds.
- Web dashboard may use a 45-second lease for ONLINE state as configured by the web application.

## UART wiring

```text
STM32 PA9  TX  ->  ESP32 GPIO16 RX
STM32 PA10 RX  <-  ESP32 GPIO17 TX
STM32 GND      --  ESP32 GND
115200 baud, 8N1
```

## Scan path

For the current Raspberry Pi W25Q64 demonstration:

1. Pi probes JEDEC and reads the W25Q64 factory unique ID and optional FIVSED metadata block.
2. Pi creates an observational logical target ID from metadata (normally SERIAL) while retaining the real factory UID separately.
3. Pi reads the real 8 MiB W25Q64 contents in bounded chunks.
4. Pi streams the bytes to STM32.
5. STM32 computes SHA-256 incrementally.
6. STM32 compares the calculated digest with the reference stored in STM32 internal Flash.
7. STM32 returns one authoritative result: `MATCH`, `HASH_MISMATCH`, `READ_ERROR`, `FIRMWARE_READ_UNSUPPORTED`, `UNREGISTERED`, `NEW_TARGET_REGISTERED`, or `REFERENCE_UPDATED` as applicable.
8. ESP32 forwards authenticated verification events to the web application and drives the physical indicators.

## Provisioning rule

A new reference is created or updated only after the local physical STM32 provisioning action has armed that operation. The Pi GUI cannot directly replace a trusted reference.
