#include <Arduino.h>
extern "C" {
#include "usb_transport.h"
}

extern "C" void usb_transport_init(void) {
    /* Native STM32duino USB CDC. Do not wait indefinitely for a host. */
    Serial.begin(115200);
}

extern "C" void fivsed_usb_write(const uint8_t *data, uint16_t len) {
    if (!data || len == 0) return;
    size_t written = 0;
    while (written < len) {
        size_t n = Serial.write(data + written, (size_t)len - written);
        if (n == 0) {
            delayMicroseconds(100);
            continue;
        }
        written += n;
    }
    Serial.flush();
}

extern "C" int fivsed_usb_read_byte(uint8_t *out, uint32_t timeout_ms) {
    if (!out) return 0;
    const uint32_t start = millis();
    while ((uint32_t)(millis() - start) < timeout_ms) {
        int value = Serial.read();
        if (value >= 0) {
            *out = (uint8_t)value;
            return 1;
        }
        delayMicroseconds(200);
    }
    return 0;
}
