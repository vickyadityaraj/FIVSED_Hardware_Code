#ifndef FIVSED_USB_TRANSPORT_H
#define FIVSED_USB_TRANSPORT_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void usb_transport_init(void);
void fivsed_usb_write(const uint8_t *data, uint16_t len);
int fivsed_usb_read_byte(uint8_t *out, uint32_t timeout_ms);

#ifdef __cplusplus
}
#endif

#endif
