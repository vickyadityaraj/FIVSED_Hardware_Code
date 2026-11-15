#ifndef STM32F411_MIN_H
#define STM32F411_MIN_H

#include <stdint.h>

#define PERIPH_BASE        0x40000000UL
#define APB1PERIPH_BASE    (PERIPH_BASE + 0x00000000UL)
#define APB2PERIPH_BASE    (PERIPH_BASE + 0x00010000UL)
#define AHB1PERIPH_BASE    (PERIPH_BASE + 0x00020000UL)

#define RCC_BASE            (AHB1PERIPH_BASE + 0x3800UL)
#define GPIOA_BASE          (AHB1PERIPH_BASE + 0x0000UL)
#define GPIOB_BASE          (AHB1PERIPH_BASE + 0x0400UL)
#define GPIOC_BASE          (AHB1PERIPH_BASE + 0x0800UL)
#define SPI1_BASE           (APB2PERIPH_BASE + 0x3000UL)
#define USART1_BASE         (APB2PERIPH_BASE + 0x1000UL)
#define USART2_BASE         (APB1PERIPH_BASE + 0x4400UL)
#define FLASH_BASE          (AHB1PERIPH_BASE + 0x3C00UL)
#define SYSTICK_BASE        0xE000E010UL

#define HSE_VALUE            25000000UL
#define FIVSED_SYSCLK_HZ     100000000UL

#define REG32(addr) (*(volatile uint32_t *)(uintptr_t)(addr))

/* Common Cortex-M4 / STM32F4 register subsets. */
#define RCC_CR               REG32(RCC_BASE + 0x00)
#define RCC_PLLCFGR          REG32(RCC_BASE + 0x04)
#define RCC_CFGR             REG32(RCC_BASE + 0x08)
#define RCC_AHB1ENR          REG32(RCC_BASE + 0x30)
#define RCC_APB1ENR          REG32(RCC_BASE + 0x40)
#define RCC_APB2ENR          REG32(RCC_BASE + 0x44)

#define FLASH_ACR            REG32(FLASH_BASE + 0x00)
#define FLASH_KEYR           REG32(FLASH_BASE + 0x04)
#define FLASH_SR             REG32(FLASH_BASE + 0x0C)
#define FLASH_CR             REG32(FLASH_BASE + 0x10)

#define SYST_CSR             REG32(SYSTICK_BASE + 0x00)
#define SYST_RVR             REG32(SYSTICK_BASE + 0x04)
#define SYST_CVR             REG32(SYSTICK_BASE + 0x08)

/* GPIO register helpers */
#define GPIO_REG(base, off)  REG32((base) + (off))
#define GPIO_MODER(base)     GPIO_REG((base), 0x00)
#define GPIO_OTYPER(base)    GPIO_REG((base), 0x04)
#define GPIO_OSPEEDR(base)   GPIO_REG((base), 0x08)
#define GPIO_PUPDR(base)     GPIO_REG((base), 0x0C)
#define GPIO_IDR(base)       GPIO_REG((base), 0x10)
#define GPIO_ODR(base)       GPIO_REG((base), 0x14)
#define GPIO_BSRR(base)      GPIO_REG((base), 0x18)
#define GPIO_AFRL(base)      GPIO_REG((base), 0x20)
#define GPIO_AFRH(base)      GPIO_REG((base), 0x24)

#define GPIOA                 GPIOA_BASE
#define GPIOB                 GPIOB_BASE
#define GPIOC                 GPIOC_BASE

/* SPI1 register subset */
#define SPI1_CR1             REG32(SPI1_BASE + 0x00)
#define SPI1_SR              REG32(SPI1_BASE + 0x08)
#define SPI1_DR              REG32(SPI1_BASE + 0x0C)

/* USART register subset */
#define USART_REG(base, off) REG32((base) + (off))
#define USART_SR(base)       USART_REG((base), 0x00)
#define USART_DR(base)       USART_REG((base), 0x04)
#define USART_BRR(base)      USART_REG((base), 0x08)
#define USART_CR1(base)      USART_REG((base), 0x0C)
#define USART_CR2(base)      USART_REG((base), 0x10)
#define USART_CR3(base)      USART_REG((base), 0x14)

/* RCC bits */
#define RCC_CR_HSEON         (1UL << 16)
#define RCC_CR_HSERDY        (1UL << 17)
#define RCC_CR_PLLON         (1UL << 24)
#define RCC_CR_PLLRDY        (1UL << 25)
#define RCC_CFGR_SW_PLL      (2UL << 0)
#define RCC_CFGR_SWS_MASK    (3UL << 2)
#define RCC_CFGR_SWS_PLL     (2UL << 2)
#define RCC_CFGR_HPRE_DIV1   (0UL << 4)
#define RCC_CFGR_PPRE1_DIV2  (4UL << 10)
#define RCC_CFGR_PPRE2_DIV1  (0UL << 13)
#define RCC_APB2ENR_SPI1EN   (1UL << 12)
#define RCC_APB2ENR_USART1EN (1UL << 4)
#define RCC_APB1ENR_USART2EN (1UL << 17)
#define RCC_APB1ENR_PWREN    (1UL << 28)

/* FLASH bits */
#define FLASH_ACR_LATENCY_5WS (5UL << 0)
#define FLASH_ACR_PRFTEN      (1UL << 8)
#define FLASH_ACR_ICEN        (1UL << 9)
#define FLASH_ACR_DCEN        (1UL << 10)
#define FLASH_SR_BSY          (1UL << 16)
#define FLASH_SR_EOP          (1UL << 0)
#define FLASH_CR_PG           (1UL << 0)
#define FLASH_CR_SER          (1UL << 1)
#define FLASH_CR_SNB_SHIFT    3
#define FLASH_CR_PSIZE_WORD   (2UL << 8)
#define FLASH_CR_STRT         (1UL << 16)
#define FLASH_CR_LOCK         (1UL << 31)

/* SPI1 bits */
#define SPI_CR1_MSTR          (1UL << 2)
#define SPI_CR1_BR_DIV4       (1UL << 3)
#define SPI_CR1_SSI           (1UL << 8)
#define SPI_CR1_SSM           (1UL << 9)
#define SPI_CR1_SPE           (1UL << 6)
#define SPI_SR_RXNE           (1UL << 0)
#define SPI_SR_TXE            (1UL << 1)
#define SPI_SR_BSY            (1UL << 7)

/* USART bits */
#define USART_SR_PE           (1UL << 0)
#define USART_SR_FE           (1UL << 1)
#define USART_SR_NE           (1UL << 2)
#define USART_SR_ORE          (1UL << 3)
#define USART_SR_RXNE         (1UL << 5)
#define USART_SR_TXE          (1UL << 7)
#define USART_SR_TC           (1UL << 6)
#define USART_CR1_RE          (1UL << 2)
#define USART_CR1_TE          (1UL << 3)
#define USART_CR1_UE          (1UL << 13)
#define USART_CR1_RXNEIE      (1UL << 5)

/* SysTick */
#define SYST_CSR_ENABLE       (1UL << 0)
#define SYST_CSR_TICKINT      (1UL << 1)
#define SYST_CSR_CLKSOURCE    (1UL << 2)

static inline void irq_disable(void) { __asm volatile("cpsid i" ::: "memory"); }
static inline void irq_enable(void)  { __asm volatile("cpsie i" ::: "memory"); }

#endif
