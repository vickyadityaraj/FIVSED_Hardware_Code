#include <Arduino.h>
extern "C" {
#include "main.h"
#include "platform.h"
#include "buttons.h"
#include "protocol.h"
#include "reference_store.h"
}
#include "usb_transport.h"

void setup() {
    /* Arduino/STM32duino initializes the system clock and USB peripheral.
       Our platform init only configures the FIVSED safety GPIO/SPI/UART. */
    system_clock_init();
    gpio_init();
    spi1_init();
    usart1_init();
    usart2_init();
    systick_init();
    reference_init();
    buttons_init();
    protocol_init();
    usb_transport_init();
    delay(100);
}

void loop() {
    int btn = buttons_poll();
    if (btn != BTN_NONE) {
        button_apply_local_action(btn);
    }

    protocol_frame_t frame;
    if (protocol_poll(&frame)) {
        protocol_handle_frame(&frame);
    }
    protocol_tick();
    delay(2);
}
