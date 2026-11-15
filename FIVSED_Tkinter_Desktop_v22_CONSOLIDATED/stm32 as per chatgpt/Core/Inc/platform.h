#ifndef FIVSED_PLATFORM_H
#define FIVSED_PLATFORM_H
#include <stdint.h>

void system_clock_init(void);
void gpio_init(void);
void spi1_init(void);
void usart1_init(void);
void usart2_init(void);
void systick_init(void);
uint32_t fivsed_millis(void);
void delay_ms(uint32_t ms);

/* Full-duplex STM32 USART1 link to ESP32. */
int esp32_uart_read_byte(uint8_t *out);
int esp32_uart_write_byte(uint8_t byte, uint32_t timeout_ms);
int esp32_uart_tx_flush(uint32_t timeout_ms);

#endif
