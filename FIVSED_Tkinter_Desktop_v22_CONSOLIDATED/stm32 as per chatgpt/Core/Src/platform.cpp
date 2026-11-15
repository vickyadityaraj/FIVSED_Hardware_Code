#include <Arduino.h>
extern "C" {
#include "stm32f411_min.h"
#include "platform.h"
}

static void gpio_pin_mode(uint32_t base, uint8_t pin, uint8_t mode, uint8_t pull, uint8_t af, uint8_t open_drain) {
    const uint32_t shift = (uint32_t)pin * 2u;
    GPIO_MODER(base) = (GPIO_MODER(base) & ~(3UL << shift)) | ((uint32_t)mode << shift);
    GPIO_PUPDR(base) = (GPIO_PUPDR(base) & ~(3UL << shift)) | ((uint32_t)pull << shift);

    if (mode == 1u) {
        GPIO_OTYPER(base) = (GPIO_OTYPER(base) & ~(1UL << pin)) | ((uint32_t)open_drain << pin);
        GPIO_OSPEEDR(base) |= (3UL << shift);
    }

    if (mode == 2u) {
        GPIO_OTYPER(base) &= ~(1UL << pin);
        GPIO_OSPEEDR(base) |= (3UL << shift);
        const uint32_t afr_shift = (uint32_t)(pin & 7u) * 4u;
        if (pin < 8u) {
            GPIO_AFRL(base) = (GPIO_AFRL(base) & ~(0xFUL << afr_shift)) | ((uint32_t)af << afr_shift);
        } else {
            GPIO_AFRH(base) = (GPIO_AFRH(base) & ~(0xFUL << afr_shift)) | ((uint32_t)af << afr_shift);
        }
    }
}

extern "C" void system_clock_init(void) {
    /* STM32duino owns the system clock/USB clock configuration. */
}

extern "C" void gpio_init(void) {
    RCC_AHB1ENR |= (1UL << 0) | (1UL << 1) | (1UL << 2);

    /* Target SPI1: PA4 CS, PA5 SCK, PA6 MISO, PA7 MOSI. */
    gpio_pin_mode(GPIOA, 4, 1, 0, 0, 0);
    gpio_pin_mode(GPIOA, 5, 2, 0, 5, 0);
    gpio_pin_mode(GPIOA, 6, 2, 0, 5, 0);
    gpio_pin_mode(GPIOA, 7, 2, 0, 5, 0);
    GPIO_BSRR(GPIOA) = (1UL << 4);

    /* Additional direct STM32 target chip-selects. */
    gpio_pin_mode(GPIOB, 0, 1, 0, 0, 0);
    gpio_pin_mode(GPIOB, 1, 1, 0, 0, 0);
    gpio_pin_mode(GPIOB, 2, 1, 0, 0, 0);
    GPIO_BSRR(GPIOB) = (1UL << 0) | (1UL << 1) | (1UL << 2);

    /* ESP32 UART: PA9 = USART1_TX, PA10 = USART1_RX, AF7, full duplex. */
    gpio_pin_mode(GPIOA, 9, 2, 0, 7, 0);
    gpio_pin_mode(GPIOA, 10, 2, 0, 7, 0);

    /* Physical security/provisioning buttons: active-low with pull-ups. */
    gpio_pin_mode(GPIOA, 0, 0, 1, 0, 0);
    gpio_pin_mode(GPIOB, 4, 0, 1, 0, 0);
    gpio_pin_mode(GPIOB, 5, 0, 1, 0, 0);
    gpio_pin_mode(GPIOA, 1, 0, 1, 0, 0);

    /* PC13 onboard LED and PC14 external alert control. */
    gpio_pin_mode(GPIOC, 13, 1, 0, 0, 0);
    gpio_pin_mode(GPIOC, 14, 1, 0, 0, 0);
    GPIO_BSRR(GPIOC) = (1UL << (13 + 16)) | (1UL << (14 + 16));
}

extern "C" void spi1_init(void) {
    RCC_APB2ENR |= RCC_APB2ENR_SPI1EN;
    /* Master, mode 0, software NSS, PCLK2/4. */
    SPI1_CR1 = SPI_CR1_MSTR | SPI_CR1_BR_DIV4 | SPI_CR1_SSM | SPI_CR1_SSI;
    SPI1_CR1 |= SPI_CR1_SPE;
}

static void usart_config(uint32_t base, uint32_t pclk_hz, uint32_t baud) {
    USART_CR1(base) = 0;
    USART_CR2(base) = 0;
    USART_CR3(base) = 0;
    USART_BRR(base) = (pclk_hz + (baud / 2UL)) / baud;
    /* 8N1, oversampling x16, full duplex TX + RX. */
    USART_CR1(base) = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}

extern "C" void usart1_init(void) {
    RCC_APB2ENR |= RCC_APB2ENR_USART1EN;
    usart_config(USART1_BASE, FIVSED_SYSCLK_HZ, 115200UL);
}

extern "C" void usart2_init(void) {
    /* Raspberry Pi control link uses native USB CDC in the current appliance. */
}

extern "C" void systick_init(void) {
    /* Arduino core owns SysTick. */
}

extern "C" uint32_t fivsed_millis(void) {
    return (uint32_t)millis();
}

extern "C" void delay_ms(uint32_t ms) {
    delay(ms);
}

extern "C" int esp32_uart_read_byte(uint8_t *out) {
    if (!out) return 0;
    const uint32_t sr = USART_SR(USART1_BASE);

    /* Clear a receive error by reading DR before returning no-data. */
    if (sr & (USART_SR_ORE | USART_SR_FE | USART_SR_NE | USART_SR_PE)) {
        *out = (uint8_t)USART_DR(USART1_BASE);
        return -1;
    }

    if ((sr & USART_SR_RXNE) == 0u) return 0;
    *out = (uint8_t)USART_DR(USART1_BASE);
    return 1;
}

extern "C" int esp32_uart_write_byte(uint8_t byte, uint32_t timeout_ms) {
    const uint32_t start = fivsed_millis();
    while ((USART_SR(USART1_BASE) & USART_SR_TXE) == 0u) {
        if ((uint32_t)(fivsed_millis() - start) >= timeout_ms) return 0;
    }
    USART_DR(USART1_BASE) = byte;
    return 1;
}

extern "C" int esp32_uart_tx_flush(uint32_t timeout_ms) {
    const uint32_t start = fivsed_millis();
    while ((USART_SR(USART1_BASE) & USART_SR_TC) == 0u) {
        if ((uint32_t)(fivsed_millis() - start) >= timeout_ms) return 0;
    }
    return 1;
}
