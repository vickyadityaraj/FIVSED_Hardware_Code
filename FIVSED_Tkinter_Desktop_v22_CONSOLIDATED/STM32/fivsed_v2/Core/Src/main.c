/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : FIVSED Core Security Authority & Heartbeat Router
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"
#include "usbd_cdc_if.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
/* USER CODE END Includes */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define REFERENCE_ADDR               0x08060000UL // Sector 7 on STM32F411 (128 KB)
#define REFERENCE_MAGIC              0x53564946UL // "FIVS"
#define REFERENCE_VERSION            2UL
#define MAX_TARGETS                  4U
#define TARGET_ID_MAX               32U
#define HASH_LEN                    32U
#define MAX_STREAM_BYTES            (16UL * 1024UL * 1024UL)

// Pi Framing Protocol (0xF5)
#define FIVSED_PI_SYNC              0xF5U
#define FIVSED_PI_VERSION           0x01U
#define MAX_PI_PAYLOAD              1024U
#define PI_HEADER_LEN               11U
#define PI_TX_FRAME_MAX             (2U + PI_HEADER_LEN + MAX_PI_PAYLOAD + 2U)

// Message Type IDs
#define MSG_HELLO_REQ               0x01U
#define MSG_STATUS_REQ              0x02U
#define MSG_SELECT_SLOT             0x03U
#define MSG_SCAN_REQ                0x04U
#define MSG_PI_HEARTBEAT            0x05U
#define MSG_ACK                     0x06U
#define MSG_NACK                    0x07U
#define MSG_STREAM_START            0x10U
#define MSG_STREAM_DATA             0x11U
#define MSG_STREAM_END              0x12U
#define MSG_STREAM_ACK              0x13U
#define MSG_HELLO_RESP              0x81U
#define MSG_STATUS_RESP             0x82U
#define MSG_HEARTBEAT_RESP          0x83U
#define MSG_SCAN_PROGRESS           0x85U
#define MSG_SCAN_RESULT             0x86U
#define MSG_COMPONENT_HEARTBEAT     0x91U
#define MSG_ERROR                   0xE0U

// ESP32 UART Protocol (Inbound 0x5A, Outbound 0xA5)
#define ESP32_INBOUND_SYNC          0x5AU
#define ESP32_INBOUND_VERSION       0x01U
#define ESP32_OUTBOUND_SYNC         0xA5U
#define ESP32_HB_INTERVAL_MS        5000UL
#define PI_HB_TIMEOUT_MS            45000UL
#define ESP32_HB_TIMEOUT_MS         35000UL

// Physical Pushbuttons
#define BUTTON_LONG_PRESS_MS        800UL
#define BUTTON_DEBOUNCE_MS          40UL
#define REGISTER_PORT               GPIOA
#define REGISTER_PIN                GPIO_PIN_0
#define REBASELINE_PORT             GPIOB
#define REBASELINE_PIN              GPIO_PIN_4
#define REVOKE_PORT                 GPIOB
#define REVOKE_PIN                  GPIO_PIN_5
#define RESTORE_PORT                GPIOA
#define RESTORE_PIN                 GPIO_PIN_1

#define ALERT_PORT                  GPIOC
#define ALERT_PIN                   GPIO_PIN_14
#define ONBOARD_LED_PORT            GPIOC
#define ONBOARD_LED_PIN             GPIO_PIN_13
/* USER CODE END PD */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
typedef struct {
    uint32_t state[8];
    uint64_t total_len;
    uint32_t buffer_len;
    uint8_t buffer[64];
} SHA256_CTX;

static const uint32_t SHA256_K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

static const uint8_t HMAC_KEY[32] = {
    0x79,0xC2,0x51,0x18,0xA7,0x2F,0x4D,0x9B,0xE3,0x11,0x63,0x8A,0xD4,0x20,0x5E,0xF1,
    0x42,0xB7,0x05,0xC8,0x33,0x6D,0x90,0x1A,0xEE,0x48,0x7C,0x14,0xD9,0x62,0xAF,0x30
};

typedef struct __attribute__((packed, aligned(4))) {
    uint8_t used;
    uint8_t reserved[3];
    uint32_t firmware_size;
    char target_id[TARGET_ID_MAX];
    uint8_t reference_hash[HASH_LEN];
    uint8_t previous_hash[HASH_LEN];
} ReferenceSlot;

typedef struct __attribute__((packed, aligned(4))) {
    uint32_t magic;
    uint32_t version;
    uint32_t sequence;
    ReferenceSlot slots[MAX_TARGETS];
    uint32_t crc32;
} ReferenceTable;

static ReferenceTable g_reference;
static uint8_t g_reference_ok = 0U;

#define USB_RING_SIZE 8192U
static uint8_t usb_ring[USB_RING_SIZE];
static volatile uint16_t usb_head = 0U, usb_tail = 0U;
static volatile uint8_t usb_overflow = 0U;

typedef enum { PI_P_SYNC = 0, PI_P_VERSION, PI_P_HEADER, PI_P_PAYLOAD, PI_P_CRC_LO, PI_P_CRC_HI } PiParserState;
static PiParserState pi_pstate = PI_P_SYNC;
static uint8_t pi_pheader[PI_HEADER_LEN], pi_ppayload[MAX_PI_PAYLOAD];
static uint8_t pi_phidx = 0;
static uint16_t pi_plen = 0, pi_pidx = 0, pi_pcrc = 0xFFFFU, pi_expected_crc = 0;
static uint32_t pi_prid = 0;
static uint16_t pi_pseq = 0;
static uint8_t pi_ptype = 0;
static uint32_t pi_plast = 0;

static uint8_t pi_tx_frame[PI_TX_FRAME_MAX];

static SHA256_CTX stream_sha;
static uint8_t stream_active = 0U, stream_non_ff = 0U;
static uint32_t stream_rid = 0U, stream_total = 0U, stream_done = 0U, stream_start_ms = 0U;
static uint8_t stream_slot = 0U;
static uint16_t stream_next_seq = 0U;
static char stream_target_id[TARGET_ID_MAX];

typedef struct { GPIO_TypeDef *port; uint16_t pin; uint8_t was_down; uint32_t down_since; uint32_t last_event; } Button;
static Button b_reg = {REGISTER_PORT, REGISTER_PIN, 0, 0, 0};
static Button b_rebase = {REBASELINE_PORT, REBASELINE_PIN, 0, 0, 0};
static Button b_revoke = {REVOKE_PORT, REVOKE_PIN, 0, 0, 0};
static Button b_restore = {RESTORE_PORT, RESTORE_PIN, 0, 0, 0};

static uint8_t active_slot = 0U;
static uint8_t register_armed = 0U;
static uint8_t rebaseline_armed = 0U;

static uint32_t pi_last_seen_ms = 0U;
static uint32_t esp32_last_seen_ms = 0U;
static uint32_t last_esp32_hb_out_ms = 0U;
static uint32_t hb_seq = 0U;
static uint32_t verification_counter = 100U;

#define UART1_RING_SIZE 2048U
static uint8_t uart1_ring[UART1_RING_SIZE];
static volatile uint16_t uart1_head = 0U, uart1_tail = 0U;
static uint8_t uart1_rx_single;

typedef enum { ESP_P_SYNC = 0, ESP_P_VERSION, ESP_P_LEN_LO, ESP_P_LEN_HI, ESP_P_PAYLOAD, ESP_P_CRC_LO, ESP_P_CRC_HI } EspParserState;
static EspParserState esp_pstate = ESP_P_SYNC;
static uint8_t esp_ppayload[512];
static uint16_t esp_plen = 0, esp_pidx = 0, esp_pcrc = 0xFFFFU, esp_expected_crc = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
void Error_Handler(void);

/* USER CODE BEGIN PFP */
static inline void secure_zero(void *ptr, size_t len) {
    volatile uint8_t *p = (volatile uint8_t *)ptr;
    while (len--) *p++ = 0U;
}

static inline uint32_t rotr32(uint32_t x, uint32_t n) { return (x >> n) | (x << (32U - n)); }
static inline uint32_t ch(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (~x & z); }
static inline uint32_t maj(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (x & z) ^ (y & z); }
static inline uint32_t bs0(uint32_t x) { return rotr32(x, 2) ^ rotr32(x, 13) ^ rotr32(x, 22); }
static inline uint32_t bs1(uint32_t x) { return rotr32(x, 6) ^ rotr32(x, 11) ^ rotr32(x, 25); }
static inline uint32_t ss0(uint32_t x) { return rotr32(x, 7) ^ rotr32(x, 18) ^ (x >> 3); }
static inline uint32_t ss1(uint32_t x) { return rotr32(x, 17) ^ rotr32(x, 19) ^ (x >> 10); }
static inline uint32_t be32(const uint8_t *p) { return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }
static inline void putbe32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }

static void SHA256_Init(SHA256_CTX *ctx);
static void SHA256_Update(SHA256_CTX *ctx, const uint8_t *data, uint32_t len);
static void SHA256_Final(SHA256_CTX *ctx, uint8_t out[32]);
static void SHA256_HMAC(const uint8_t *key, uint32_t key_len, const uint8_t *msg, uint32_t msg_len, uint8_t out[32]);

static uint16_t CRC16_Update(uint16_t crc, uint8_t b);
static void Pi_USBSendFrame(uint8_t type, uint32_t rid, uint16_t seq, const uint8_t *payload, uint16_t len);
static void Pi_USBSendJSON(uint8_t type, uint32_t rid, uint16_t seq, const char *json);
static void ESP32_SendAuthenticatedPayload(const uint8_t *payload, uint16_t len);
static void ESP32_SendComponentHeartbeat(void);
static void AlertSet(uint8_t on);

static inline bool provisioning_register_armed(void) {
    return (register_armed != 0U);
}

static inline void provisioning_clear_register(void) {
    register_armed = 0U;
}
/* USER CODE END PFP */

/* USER CODE BEGIN 0 */
static void SHA256_Transform(SHA256_CTX *ctx, const uint8_t block[64]) {
    uint32_t w[64];
    for (uint32_t i = 0; i < 16; i++) w[i] = be32(block + i * 4U);
    for (uint32_t i = 16; i < 64; i++) w[i] = ss1(w[i - 2]) + w[i - 7] + ss0(w[i - 15]) + w[i - 16];
    uint32_t a = ctx->state[0], b = ctx->state[1], c = ctx->state[2], d = ctx->state[3];
    uint32_t e = ctx->state[4], f = ctx->state[5], g = ctx->state[6], h = ctx->state[7];
    for (uint32_t i = 0; i < 64; i++) {
        uint32_t t1 = h + bs1(e) + ch(e, f, g) + SHA256_K[i] + w[i];
        uint32_t t2 = bs0(a) + maj(a, b, c);
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
    secure_zero(w, sizeof(w));
}

static void SHA256_Init(SHA256_CTX *ctx) {
    static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(ctx->state, iv, sizeof(iv));
    ctx->total_len = 0U;
    ctx->buffer_len = 0U;
    memset(ctx->buffer, 0, sizeof(ctx->buffer));
}

static void SHA256_Update(SHA256_CTX *ctx, const uint8_t *data, uint32_t len) {
    if (!ctx || (!data && len)) return;
    ctx->total_len += (uint64_t)len;
    while (len) {
        uint32_t take = 64U - ctx->buffer_len;
        if (take > len) take = len;
        memcpy(ctx->buffer + ctx->buffer_len, data, take);
        ctx->buffer_len += take;
        data += take;
        len -= take;
        if (ctx->buffer_len == 64U) {
            SHA256_Transform(ctx, ctx->buffer);
            ctx->buffer_len = 0U;
        }
    }
}

static void SHA256_Final(SHA256_CTX *ctx, uint8_t out[32]) {
    uint64_t bit_len = ctx->total_len * 8ULL;
    uint8_t pad[128] = {0};
    uint8_t lenbuf[8];
    uint32_t pad_len = (ctx->buffer_len < 56U) ? (56U - ctx->buffer_len) : (120U - ctx->buffer_len);
    pad[0] = 0x80U;
    SHA256_Update(ctx, pad, pad_len);
    for (int i = 0; i < 8; i++) lenbuf[7 - i] = (uint8_t)(bit_len >> (8 * i));
    SHA256_Update(ctx, lenbuf, 8U);
    for (int i = 0; i < 8; i++) putbe32(out + i * 4, ctx->state[i]);
    secure_zero(pad, sizeof(pad));
    secure_zero(lenbuf, sizeof(lenbuf));
}

static void SHA256_HMAC(const uint8_t *key, uint32_t key_len, const uint8_t *msg, uint32_t msg_len, uint8_t out[32]) {
    uint8_t k0[64] = {0}, ipad[64], opad[64], inner[32];
    SHA256_CTX ctx;
    if (key_len > 64U) {
        SHA256_CTX kc;
        SHA256_Init(&kc);
        SHA256_Update(&kc, key, key_len);
        SHA256_Final(&kc, k0);
        secure_zero(&kc, sizeof(kc));
        key_len = 32U;
    } else if (key_len) {
        memcpy(k0, key, key_len);
    }
    for (int i = 0; i < 64; i++) {
        ipad[i] = (uint8_t)(k0[i] ^ 0x36U);
        opad[i] = (uint8_t)(k0[i] ^ 0x5CU);
    }
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, ipad, 64U);
    SHA256_Update(&ctx, msg, msg_len);
    SHA256_Final(&ctx, inner);
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, opad, 64U);
    SHA256_Update(&ctx, inner, 32U);
    SHA256_Final(&ctx, out);
    secure_zero(k0, sizeof(k0));
    secure_zero(ipad, sizeof(ipad));
    secure_zero(opad, sizeof(opad));
    secure_zero(inner, sizeof(inner));
    secure_zero(&ctx, sizeof(ctx));
}

static uint32_t CRC32_Calc(const uint8_t *data, uint32_t len) {
    uint32_t crc = 0xFFFFFFFFUL;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint32_t b = 0; b < 8; b++) crc = (crc & 1U) ? ((crc >> 1) ^ 0xEDB88320UL) : (crc >> 1);
    }
    return ~crc;
}

static uint32_t ReferenceCRC(const ReferenceTable *t) {
    return CRC32_Calc((const uint8_t *)t, (uint32_t)offsetof(ReferenceTable, crc32));
}

static int ReferenceErased(void) {
    const uint8_t *p = (const uint8_t *)REFERENCE_ADDR;
    for (uint32_t i = 0; i < sizeof(ReferenceTable); i++) if (p[i] != 0xFFU) return 0;
    return 1;
}

static int ReferenceSave(void) {
    FLASH_EraseInitTypeDef er = {0};
    uint32_t sector_error = 0U;
    g_reference.magic = REFERENCE_MAGIC;
    g_reference.version = REFERENCE_VERSION;
    g_reference.sequence++;
    g_reference.crc32 = ReferenceCRC(&g_reference);

    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    er.TypeErase = FLASH_TYPEERASE_SECTORS;
    er.Sector = FLASH_SECTOR_7;
    er.NbSectors = 1;
    er.VoltageRange = FLASH_VOLTAGE_RANGE_3;

    if (HAL_FLASHEx_Erase(&er, &sector_error) != HAL_OK) {
        HAL_FLASH_Lock();
        return -2;
    }

    const uint32_t *src = (const uint32_t *)&g_reference;
    uint32_t words = (uint32_t)(sizeof(ReferenceTable) / 4U);
    for (uint32_t i = 0; i < words; i++) {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, REFERENCE_ADDR + i * 4U, src[i]) != HAL_OK) {
            HAL_FLASH_Lock();
            return -3;
        }
    }
    HAL_FLASH_Lock();
    return (memcmp((const void *)REFERENCE_ADDR, &g_reference, sizeof(g_reference)) == 0) ? 0 : -4;
}

static void ReferenceInit(void) {
    const ReferenceTable *stored = (const ReferenceTable *)REFERENCE_ADDR;
    if (ReferenceErased()) {
        memset(&g_reference, 0, sizeof(g_reference));
        g_reference.magic = REFERENCE_MAGIC;
        g_reference.version = REFERENCE_VERSION;
        g_reference.sequence = 0U;
        g_reference.crc32 = ReferenceCRC(&g_reference);
        g_reference_ok = 1U;
        return;
    }
    if (stored->magic == REFERENCE_MAGIC && stored->version == REFERENCE_VERSION && stored->crc32 == ReferenceCRC(stored)) {
        memcpy(&g_reference, stored, sizeof(g_reference));
        g_reference_ok = 1U;
    } else {
        // Default to blank clean table rather than asserting a fatal error
        memset(&g_reference, 0, sizeof(g_reference));
        g_reference.magic = REFERENCE_MAGIC;
        g_reference.version = REFERENCE_VERSION;
        g_reference.sequence = 0U;
        g_reference.crc32 = ReferenceCRC(&g_reference);
        g_reference_ok = 1U;
    }
}

static int ReferenceFind(const char *target_id) {
    if (!target_id || !g_reference_ok) return -1;
    for (uint8_t i = 0; i < MAX_TARGETS; i++) {
        if (g_reference.slots[i].used && strncmp(g_reference.slots[i].target_id, target_id, TARGET_ID_MAX) == 0) return (int)i;
    }
    return -1;
}

static int ReferenceRegister(uint8_t slot, const char *id, const uint8_t digest[32], uint32_t size) {
    if (!g_reference_ok || slot >= MAX_TARGETS || !id || !digest) return -1;
    if (g_reference.slots[slot].used) return -2;
    if (ReferenceFind(id) >= 0) return -3;

    memset(&g_reference.slots[slot], 0, sizeof(g_reference.slots[slot]));
    g_reference.slots[slot].used = 1U;
    g_reference.slots[slot].firmware_size = size;
    strncpy(g_reference.slots[slot].target_id, id, TARGET_ID_MAX - 1U);
    memcpy(g_reference.slots[slot].reference_hash, digest, 32U);
    memcpy(g_reference.slots[slot].previous_hash, digest, 32U);

    int rc = ReferenceSave();
    if (rc) g_reference_ok = 0U;
    return rc;
}

static int ReferenceUpdate(uint8_t slot, const uint8_t digest[32], uint32_t size) {
    if (!g_reference_ok || slot >= MAX_TARGETS || !g_reference.slots[slot].used) return -1;
    memcpy(g_reference.slots[slot].previous_hash, g_reference.slots[slot].reference_hash, 32U);
    memcpy(g_reference.slots[slot].reference_hash, digest, 32U);
    g_reference.slots[slot].firmware_size = size;

    int rc = ReferenceSave();
    if (rc) g_reference_ok = 0U;
    return rc;
}

static int ReferenceRevoke(uint8_t slot) {
    if (!g_reference_ok || slot >= MAX_TARGETS || !g_reference.slots[slot].used) return -1;
    memset(&g_reference.slots[slot], 0, sizeof(g_reference.slots[slot]));
    int rc = ReferenceSave();
    if (rc) g_reference_ok = 0U;
    return rc;
}

static int ReferenceRestore(uint8_t slot) {
    if (!g_reference_ok || slot >= MAX_TARGETS || !g_reference.slots[slot].used) return -1;
    uint8_t t[32];
    memcpy(t, g_reference.slots[slot].reference_hash, 32);
    memcpy(g_reference.slots[slot].reference_hash, g_reference.slots[slot].previous_hash, 32);
    memcpy(g_reference.slots[slot].previous_hash, t, 32);
    secure_zero(t, sizeof(t));
    int rc = ReferenceSave();
    if (rc) g_reference_ok = 0U;
    return rc;
}

void FIVSED_USB_RxFeed(const uint8_t *data, uint32_t len) {
    if (!data) return;
    for (uint32_t i = 0; i < len; i++) {
        uint16_t next = (uint16_t)((usb_head + 1U) % USB_RING_SIZE);
        if (next == usb_tail) {
            usb_overflow = 1U;
            break;
        }
        usb_ring[usb_head] = data[i];
        usb_head = next;
    }
}

static int USBReadByte(uint8_t *b) {
    if (usb_tail == usb_head) return 0;
    *b = usb_ring[usb_tail];
    usb_tail = (uint16_t)((usb_tail + 1U) % USB_RING_SIZE);
    return 1;
}

static uint16_t CRC16_Update(uint16_t crc, uint8_t b) {
    crc ^= (uint16_t)b << 8;
    for (uint8_t i = 0; i < 8; i++) crc = (crc & 0x8000U) ? (uint16_t)((crc << 1) ^ 0x1021U) : (uint16_t)(crc << 1);
    return crc;
}

static void Pi_USBSendFrame(uint8_t type, uint32_t rid, uint16_t seq, const uint8_t *payload, uint16_t len) {
    if (len > MAX_PI_PAYLOAD) return;
    uint32_t p = 0U;
    pi_tx_frame[p++] = FIVSED_PI_SYNC;
    pi_tx_frame[p++] = FIVSED_PI_VERSION;
    pi_tx_frame[p++] = type;
    pi_tx_frame[p++] = 0;
    pi_tx_frame[p++] = 0;
    pi_tx_frame[p++] = (uint8_t)rid;
    pi_tx_frame[p++] = (uint8_t)(rid >> 8);
    pi_tx_frame[p++] = (uint8_t)(rid >> 16);
    pi_tx_frame[p++] = (uint8_t)(rid >> 24);
    pi_tx_frame[p++] = (uint8_t)seq;
    pi_tx_frame[p++] = (uint8_t)(seq >> 8);
    pi_tx_frame[p++] = (uint8_t)len;
    pi_tx_frame[p++] = (uint8_t)(len >> 8);

    if (len && payload) {
        memcpy(pi_tx_frame + p, payload, len);
        p += len;
    }

    uint16_t crc = 0xFFFFU;
    for (uint32_t i = 1; i < p; i++) crc = CRC16_Update(crc, pi_tx_frame[i]);
    pi_tx_frame[p++] = (uint8_t)crc;
    pi_tx_frame[p++] = (uint8_t)(crc >> 8);

    uint32_t deadline = HAL_GetTick() + 200U;
    while (HAL_GetTick() < deadline) {
        uint8_t rc = CDC_Transmit_FS(pi_tx_frame, (uint16_t)p);
        if (rc == USBD_OK) return;
        HAL_Delay(1U);
    }
}

static void Pi_USBSendJSON(uint8_t type, uint32_t rid, uint16_t seq, const char *json) {
    if (json && strlen(json) <= MAX_PI_PAYLOAD) {
        Pi_USBSendFrame(type, rid, seq, (const uint8_t *)json, (uint16_t)strlen(json));
    }
}

static void ESP32_SendAuthenticatedPayload(const uint8_t *payload, uint16_t len) {
    if (!payload || !len || len > 1024) return;
    uint8_t mac[32];
    uint8_t sync = ESP32_OUTBOUND_SYNC;
    uint8_t h[2] = {(uint8_t)(len & 0xFF), (uint8_t)((len >> 8) & 0xFF)};
    SHA256_HMAC(HMAC_KEY, 32U, payload, len, mac);
    HAL_UART_Transmit(&huart1, &sync, 1U, 50U);
    HAL_UART_Transmit(&huart1, h, 2U, 50U);
    HAL_UART_Transmit(&huart1, (uint8_t *)payload, len, 500U);
    HAL_UART_Transmit(&huart1, mac, 32U, 200U);
    secure_zero(mac, sizeof(mac));
}

static void ReportVerdictBoth(uint32_t rid, uint8_t slot, const char *result, const char *status, const char *reason, uint32_t size, uint32_t duration) {
    verification_counter++;
    char j[512];
    snprintf(j, sizeof(j),
        "{\"version\":1,\"event\":\"FIRMWARE_VERIFICATION\",\"source\":\"STM32\",\"decision_authority\":\"STM32\","
        "\"verification_id\":%lu,\"scan_id\":%lu,\"slot\":%u,\"result\":\"%s\",\"status\":\"%s\","
        "\"firmware_size\":%lu,\"duration_ms\":%lu,\"reason\":\"%s\",\"hash_disclosure\":false}",
        (unsigned long)verification_counter, (unsigned long)rid, (unsigned)slot, result, status,
        (unsigned long)size, (unsigned long)duration, reason ? reason : "");

    Pi_USBSendJSON(MSG_SCAN_RESULT, rid, 0, j);
    ESP32_SendAuthenticatedPayload((const uint8_t *)j, (uint16_t)strlen(j));
}

static void ESP32_SendComponentHeartbeat(void) {
    uint32_t now = HAL_GetTick();
    bool pi = (pi_last_seen_ms != 0U && (uint32_t)(now - pi_last_seen_ms) <= PI_HB_TIMEOUT_MS);
    bool esp = (esp32_last_seen_ms != 0U && (uint32_t)(now - esp32_last_seen_ms) <= ESP32_HB_TIMEOUT_MS);

    char j[320];
    int n = snprintf(j, sizeof(j),
        "{\"version\":1,\"event\":\"COMPONENT_HEARTBEAT\",\"source\":\"STM32\",\"status\":\"ACTIVE\","
        "\"stm32_active\":true,\"raspberry_pi_active\":%s,\"esp32_active\":%s,"
        "\"stm32_uptime_ms\":%lu,\"pi_last_seen_ms\":%lu,\"esp32_last_seen_ms\":%lu,\"sequence\":%lu}",
        pi ? "true" : "false", esp ? "true" : "false", (unsigned long)now,
        (unsigned long)pi_last_seen_ms, (unsigned long)esp32_last_seen_ms, (unsigned long)(++hb_seq));
    if (n > 0 && n < (int)sizeof(j)) ESP32_SendAuthenticatedPayload((const uint8_t *)j, (uint16_t)n);
}

static void AlertSet(uint8_t on) {
    HAL_GPIO_WritePin(ALERT_PORT, ALERT_PIN, on ? GPIO_PIN_SET : GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ONBOARD_LED_PORT, ONBOARD_LED_PIN, on ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

static void ButtonAction(uint8_t action) {
    if (!g_reference_ok) { AlertSet(1); return; }
    if (action == 1U) { register_armed = 1; rebaseline_armed = 0; }
    else if (action == 2U) { rebaseline_armed = 1; register_armed = 0; }
    else if (action == 3U) { register_armed = 0; rebaseline_armed = 0; (void)ReferenceRevoke(active_slot); }
    else if (action == 4U) { register_armed = 0; rebaseline_armed = 0; (void)ReferenceRestore(active_slot); }
}

static void ButtonPoll(Button *b, uint8_t action) {
    uint8_t down = (HAL_GPIO_ReadPin(b->port, b->pin) == GPIO_PIN_RESET) ? 1U : 0U;
    uint32_t now = HAL_GetTick();
    if (down && !b->was_down) {
        b->was_down = 1U;
        b->down_since = now;
        return;
    }
    if (!down && b->was_down) {
        uint32_t held = now - b->down_since;
        b->was_down = 0U;
        if (held >= BUTTON_LONG_PRESS_MS && (uint32_t)(now - b->last_event) >= BUTTON_DEBOUNCE_MS) {
            b->last_event = now;
            ButtonAction(action);
        }
    }
}

static void ButtonsPoll(void) {
    ButtonPoll(&b_reg, 1U);
    ButtonPoll(&b_rebase, 2U);
    ButtonPoll(&b_revoke, 3U);
    ButtonPoll(&b_restore, 4U);
}

static void StreamReset(void) {
    secure_zero(&stream_sha, sizeof(stream_sha));
    stream_active = 0;
    stream_non_ff = 0;
    stream_rid = 0;
    stream_total = 0;
    stream_done = 0;
    stream_start_ms = 0;
    stream_slot = 0;
    stream_next_seq = 0;
    secure_zero(stream_target_id, sizeof(stream_target_id));
}

static int ParseU32(const char *json, const char *key, uint32_t *out) {
    char needle[48];
    int n = snprintf(needle, sizeof(needle), "\"%s\"", key);
    if (n <= 0 || n >= (int)sizeof(needle)) return 0;
    const char *p = strstr(json, needle);
    if (!p) return 0;
    p = strchr(p, ':');
    if (!p) return 0;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    if (*p < '0' || *p > '9') return 0;
    uint32_t v = 0;
    do { v = v * 10U + (uint32_t)(*p - '0'); p++; } while (*p >= '0' && *p <= '9');
    *out = v;
    return 1;
}

static int ParseString(const char *json, const char *key, char *out, uint32_t out_len) {
    char needle[48];
    int n = snprintf(needle, sizeof(needle), "\"%s\"", key);
    if (n <= 0 || n >= (int)sizeof(needle)) return 0;
    const char *p = strstr(json, needle);
    if (!p) return 0;
    p = strchr(p, ':');
    if (!p) return 0;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    if (*p != '\"') return 0;
    p++;
    uint32_t i = 0;
    while (*p && *p != '\"') {
        if (*p == '\\' || i + 1U >= out_len) return 0;
        out[i++] = *p++;
    }
    if (*p != '\"') return 0;
    out[i] = '\0';
    return (i > 0U);
}

/* ==============================================================================
 * StreamStart: UPDATED PROVISIONING LOGIC
 * ============================================================================== */
static void StreamStart(uint32_t rid, uint16_t seq, const uint8_t *payload, uint16_t len) {
    char json[MAX_PI_PAYLOAD + 1];
    uint32_t slot = 0, total = 0;
    char id[TARGET_ID_MAX] = {0};

    // 1. Basic Structural & Parameter Validation
    if (len >= sizeof(json)) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"PAYLOAD_TOO_LARGE\"}");
        return;
    }
    memcpy(json, payload, len);
    json[len] = '\0';

    if (!ParseU32(json, "slot", &slot) || slot >= MAX_TARGETS) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"INVALID_TARGET_SLOT\"}");
        return;
    }
    if (!ParseU32(json, "total_bytes", &total) || total == 0 || total > MAX_STREAM_BYTES) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"INVALID_TOTAL_BYTES\"}");
        return;
    }
    if (!ParseString(json, "target_id", id, sizeof(id)) || strlen(id) == 0) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"MISSING_TARGET_ID\"}");
        return;
    }

    if (!g_reference_ok) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"REFERENCE_STORAGE_CORRUPT\"}");
        return;
    }

    // 2. Unregistered vs. Registered Target Logic
    int existing_slot = ReferenceFind(id);
    bool slot_occupied = (g_reference.slots[slot].used != 0);

    if (!slot_occupied && existing_slot < 0) {
        // CASE: Target & Slot are UNREGISTERED
        // Strictly require physical REGISTER button to be armed!
        if (!provisioning_register_armed()) {
            Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"PHYSICAL_REGISTER_REQUIRED\"}");
            return;
        }
        // Physical REGISTER is armed -> Allow stream start!
    } else {
        // CASE: Target or Slot is REGISTERED
        if (existing_slot >= 0 && existing_slot != (int)slot) {
            Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"TARGET_SLOT_MISMATCH\"}");
            return;
        }
        if (slot_occupied) {
            if (strncmp(g_reference.slots[slot].target_id, id, TARGET_ID_MAX) != 0) {
                Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"TARGET_ID_MISMATCH\"}");
                return;
            }
        }
    }

    // 3. Initialize Streaming Session
    StreamReset();
    stream_active = 1;
    stream_rid = rid;
    stream_slot = (uint8_t)slot;
    stream_total = total;
    stream_done = 0;
    stream_start_ms = HAL_GetTick();
    stream_next_seq = 0;
    strncpy(stream_target_id, id, TARGET_ID_MAX - 1U);
    SHA256_Init(&stream_sha);

    Pi_USBSendJSON(MSG_STREAM_ACK, rid, seq, "{\"accepted\":true,\"stage\":\"STREAMING_TO_STM32\"}");
}

static void StreamData(uint32_t rid, uint16_t seq, const uint8_t *payload, uint16_t len) {
    if (!stream_active || rid != stream_rid || seq != stream_next_seq) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"STREAM_SEQUENCE_ERROR\"}");
        return;
    }
    if (!len || stream_done + (uint32_t)len > stream_total) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"STREAM_LENGTH_ERROR\"}");
        return;
    }

    SHA256_Update(&stream_sha, payload, len);
    for (uint16_t i = 0; i < len; i++) {
        if (payload[i] != 0xFFU) { stream_non_ff = 1; break; }
    }
    stream_done += len;
    stream_next_seq++;

    char ack[180];
    int n = snprintf(ack, sizeof(ack), "{\"bytes_processed\":%lu,\"total_bytes\":%lu}",
                     (unsigned long)stream_done, (unsigned long)stream_total);
    if (n > 0 && n < (int)sizeof(ack)) Pi_USBSendJSON(MSG_STREAM_ACK, rid, seq, ack);
}

static void StreamEnd(uint32_t rid, uint16_t seq) {
    if (!stream_active || rid != stream_rid || seq != stream_next_seq) {
        Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"STREAM_END_SEQUENCE_ERROR\"}");
        return;
    }
    uint8_t digest[32];
    uint32_t size = stream_done, duration = HAL_GetTick() - stream_start_ms;
    uint8_t slot = stream_slot;
    char id[TARGET_ID_MAX];
    strncpy(id, stream_target_id, TARGET_ID_MAX - 1U);
    id[TARGET_ID_MAX - 1U] = '\0';

    if (stream_done != stream_total) {
        Pi_USBSendJSON(MSG_STREAM_ACK, rid, seq, "{\"complete\":false,\"accepted\":false}");
        ReportVerdictBoth(rid, slot, "READ_ERROR", "FAIL", "Incomplete firmware stream", size, duration);
        AlertSet(1);
        StreamReset();
        return;
    }
    if (!stream_non_ff) {
        Pi_USBSendJSON(MSG_STREAM_ACK, rid, seq, "{\"complete\":false,\"accepted\":false}");
        ReportVerdictBoth(rid, slot, "READ_ERROR", "FAIL", "Firmware image is all 0xFF", size, duration);
        AlertSet(1);
        StreamReset();
        return;
    }

    SHA256_Final(&stream_sha, digest);
    Pi_USBSendJSON(MSG_STREAM_ACK, rid, seq, "{\"complete\":true,\"accepted\":true}");

    if (!g_reference_ok) {
        ReportVerdictBoth(rid, slot, "READ_ERROR", "FAIL", "STM32 reference table is invalid", size, duration);
        secure_zero(digest, sizeof(digest));
        StreamReset();
        AlertSet(1);
        return;
    }

    int ref_slot = ReferenceFind(id);
    if (ref_slot < 0) {
        if (provisioning_register_armed() && !g_reference.slots[slot].used) {
            int rc = ReferenceRegister(slot, id, digest, size);
            provisioning_clear_register();
            if (rc == 0) {
                ReportVerdictBoth(rid, slot, "NEW_TARGET_REGISTERED", "PASS", "Trusted reference created inside STM32 flash", size, duration);
                AlertSet(0);
            } else {
                ReportVerdictBoth(rid, slot, "READ_ERROR", "FAIL", "STM32 reference storage write failed", size, duration);
                AlertSet(1);
            }
        } else {
            ReportVerdictBoth(rid, slot, "UNREGISTERED", "FAIL", "Target measured but has no trusted reference", size, duration);
            AlertSet(1);
        }
    } else if (rebaseline_armed) {
        int rc = ReferenceUpdate((uint8_t)ref_slot, digest, size);
        rebaseline_armed = 0U;
        if (rc == 0) {
            ReportVerdictBoth(rid, slot, "REFERENCE_UPDATED", "PASS", "Trusted reference updated by physical STM32 action", size, duration);
            AlertSet(0);
        } else {
            ReportVerdictBoth(rid, slot, "READ_ERROR", "FAIL", "STM32 reference storage write failed", size, duration);
            AlertSet(1);
        }
    } else {
        const ReferenceSlot *ref = &g_reference.slots[ref_slot];
        if (ref->firmware_size != size) {
            ReportVerdictBoth(rid, slot, "HASH_MISMATCH", "FAIL", "Firmware size differs from STM32 reference", size, duration);
            AlertSet(1);
        } else if (memcmp(digest, ref->reference_hash, 32U) == 0) {
            ReportVerdictBoth(rid, slot, "MATCH", "PASS", "Firmware measurement matches STM32 trusted reference", size, duration);
            AlertSet(0);
        } else {
            ReportVerdictBoth(rid, slot, "HASH_MISMATCH", "FAIL", "Firmware measurement differs from STM32 trusted reference", size, duration);
            AlertSet(1);
        }
    }
    secure_zero(digest, sizeof(digest));
    StreamReset();
}

static void HandlePiFrame(uint8_t type, uint32_t rid, uint16_t seq, const uint8_t *payload, uint16_t len) {
    char json[MAX_PI_PAYLOAD + 1];
    if (type != MSG_STREAM_DATA) {
        memcpy(json, payload, len);
        json[len] = '\0';
    }

    switch (type) {
        case MSG_HELLO_REQ:
            Pi_USBSendJSON(MSG_HELLO_RESP, rid, 0,
                "{\"protocol\":1,\"controller\":\"STM32F411CEU6\",\"role\":\"SECURITY_AUTHORITY\"}");
            break;

        case MSG_STATUS_REQ: {
            char out[MAX_PI_PAYLOAD];
            size_t pos = 0;
            int n = snprintf(out + pos, sizeof(out) - pos, "{\"controller\":\"STM32F411CEU6\",\"role\":\"SECURITY_AUTHORITY\",\"slots\":[");
            if (n < 0 || (size_t)n >= sizeof(out) - pos) return;
            pos += (size_t)n;
            for (uint8_t i = 0; i < MAX_TARGETS; i++) {
                if (i) out[pos++] = ',';
                const ReferenceSlot *s = &g_reference.slots[i];
                n = snprintf(out + pos, sizeof(out) - pos,
                    "{\"slot\":%u,\"registered\":%s,\"target_id\":\"%s\",\"firmware_size\":%lu,\"reference_state\":\"%s\"}",
                    (unsigned)i, s->used ? "true" : "false", s->used ? s->target_id : "",
                    (unsigned long)(s->used ? s->firmware_size : 0U),
                    s->used ? "TRUSTED_REFERENCE_STORED" : "UNREGISTERED");
                if (n < 0 || (size_t)n >= sizeof(out) - pos) return;
                pos += (size_t)n;
            }
            n = snprintf(out + pos, sizeof(out) - pos, "]}");
            if (n < 0 || (size_t)n >= sizeof(out) - pos) return;
            pos += (size_t)n;
            Pi_USBSendFrame(MSG_STATUS_RESP, rid, 0, (const uint8_t *)out, (uint16_t)pos);
            break;
        }

        case MSG_SELECT_SLOT: {
            uint32_t s;
            if (ParseU32(json, "slot", &s) && s < MAX_TARGETS) {
                active_slot = (uint8_t)s;
                Pi_USBSendJSON(MSG_ACK, rid, 0, "{\"ok\":true}");
            } else {
                Pi_USBSendJSON(MSG_NACK, rid, 0, "{\"error\":\"INVALID_TARGET_SLOT\"}");
            }
            break;
        }

        case MSG_PI_HEARTBEAT: {
            pi_last_seen_ms = HAL_GetTick();
            bool esp_active = (esp32_last_seen_ms != 0U && (HAL_GetTick() - esp32_last_seen_ms) <= ESP32_HB_TIMEOUT_MS);
            char resp[160];
            snprintf(resp, sizeof(resp),
                "{\"pi_active\":true,\"stm32_active\":true,\"esp32_active\":%s,\"esp32_last_seen_ms\":%lu}",
                esp_active ? "true" : "false", (unsigned long)esp32_last_seen_ms);
            Pi_USBSendJSON(MSG_HEARTBEAT_RESP, rid, seq, resp);
            break;
        }

        case MSG_SCAN_REQ:
            Pi_USBSendJSON(MSG_ACK, rid, seq, "{\"status\":\"SCAN_REQUEST_ACCEPTED\",\"message\":\"Initiate firmware stream\"}");
            break;

        case MSG_STREAM_START:
            StreamStart(rid, seq, payload, len);
            break;

        case MSG_STREAM_DATA:
            StreamData(rid, seq, payload, len);
            break;

        case MSG_STREAM_END:
            StreamEnd(rid, seq);
            break;

        default:
            Pi_USBSendJSON(MSG_NACK, rid, seq, "{\"error\":\"UNKNOWN_MESSAGE_TYPE\"}");
            break;
    }
}

static void ProcessPiUSBBytes(void) {
    uint8_t b;
    while (USBReadByte(&b)) {
        uint32_t now = HAL_GetTick();
        if (pi_pstate != PI_P_SYNC && (uint32_t)(now - pi_plast) > 2000U) pi_pstate = PI_P_SYNC;
        pi_plast = now;

        switch (pi_pstate) {
            case PI_P_SYNC:
                if (b == FIVSED_PI_SYNC) pi_pstate = PI_P_VERSION;
                break;
            case PI_P_VERSION:
                if (b != FIVSED_PI_VERSION) {
                    pi_pstate = PI_P_SYNC;
                } else {
                    pi_pcrc = CRC16_Update(0xFFFFU, b);
                    pi_phidx = 0;
                    pi_pstate = PI_P_HEADER;
                }
                break;
            case PI_P_HEADER:
                pi_pheader[pi_phidx++] = b;
                pi_pcrc = CRC16_Update(pi_pcrc, b);
                if (pi_phidx == PI_HEADER_LEN) {
                    pi_ptype = pi_pheader[0];
                    pi_prid  = (uint32_t)pi_pheader[3] | ((uint32_t)pi_pheader[4] << 8) |
                               ((uint32_t)pi_pheader[5] << 16) | ((uint32_t)pi_pheader[6] << 24);
                    pi_pseq  = (uint16_t)pi_pheader[7] | ((uint16_t)pi_pheader[8] << 8);
                    pi_plen  = (uint16_t)pi_pheader[9] | ((uint16_t)pi_pheader[10] << 8);
                    pi_pidx  = 0;
                    if (pi_plen > MAX_PI_PAYLOAD) {
                        Pi_USBSendJSON(MSG_NACK, pi_prid, pi_pseq, "{\"error\":\"PAYLOAD_TOO_LARGE\"}");
                        pi_pstate = PI_P_SYNC;
                    } else {
                        pi_pstate = pi_plen ? PI_P_PAYLOAD : PI_P_CRC_LO;
                    }
                }
                break;
            case PI_P_PAYLOAD:
                pi_ppayload[pi_pidx++] = b;
                pi_pcrc = CRC16_Update(pi_pcrc, b);
                if (pi_pidx == pi_plen) pi_pstate = PI_P_CRC_LO;
                break;
            case PI_P_CRC_LO:
                pi_expected_crc = b;
                pi_pstate = PI_P_CRC_HI;
                break;
            case PI_P_CRC_HI:
                pi_expected_crc |= (uint16_t)b << 8;
                if (pi_pcrc == pi_expected_crc) {
                    HandlePiFrame(pi_ptype, pi_prid, pi_pseq, pi_ppayload, pi_plen);
                } else {
                    Pi_USBSendJSON(MSG_NACK, pi_prid, pi_pseq, "{\"error\":\"CRC16_MISMATCH\"}");
                }
                pi_pstate = PI_P_SYNC;
                break;
            default:
                pi_pstate = PI_P_SYNC;
                break;
        }
    }
    if (usb_overflow) {
        usb_overflow = 0;
        pi_pstate = PI_P_SYNC;
        Pi_USBSendJSON(MSG_NACK, 0, 0, "{\"error\":\"USB_RX_OVERFLOW\"}");
    }
}

static void HandleEsp32Frame(const uint8_t *payload, uint16_t len) {
    char json[513];
    if (len >= sizeof(json)) return;
    memcpy(json, payload, len);
    json[len] = '\0';

    if (strstr(json, "\"ESP32_HEARTBEAT\"") != NULL) {
        esp32_last_seen_ms = HAL_GetTick();

        char ack[256];
        snprintf(ack, sizeof(ack),
            "{\"version\":1,\"event\":\"ESP32_HEARTBEAT_ACK\",\"source\":\"STM32\","
            "\"status\":\"ACK\",\"message\":\"ACK: ESP32_ACTIVE\",\"stm32_active\":true,\"sequence\":%lu}",
            (unsigned long)(++hb_seq));
        ESP32_SendAuthenticatedPayload((const uint8_t *)ack, (uint16_t)strlen(ack));
    }
}

static void ProcessEsp32UartBytes(void) {
    while (uart1_tail != uart1_head) {
        uint8_t b = uart1_ring[uart1_tail];
        uart1_tail = (uint16_t)((uart1_tail + 1U) % UART1_RING_SIZE);

        switch (esp_pstate) {
            case ESP_P_SYNC:
                if (b == ESP32_INBOUND_SYNC) esp_pstate = ESP_P_VERSION;
                break;
            case ESP_P_VERSION:
                if (b != ESP32_INBOUND_VERSION) {
                    esp_pstate = ESP_P_SYNC;
                } else {
                    esp_pcrc = CRC16_Update(0xFFFFU, b);
                    esp_pstate = ESP_P_LEN_LO;
                }
                break;
            case ESP_P_LEN_LO:
                esp_plen = b;
                esp_pcrc = CRC16_Update(esp_pcrc, b);
                esp_pstate = ESP_P_LEN_HI;
                break;
            case ESP_P_LEN_HI:
                esp_plen |= ((uint16_t)b << 8);
                esp_pcrc = CRC16_Update(esp_pcrc, b);
                esp_pidx = 0;
                if (esp_plen > sizeof(esp_ppayload)) {
                    esp_pstate = ESP_P_SYNC;
                } else {
                    esp_pstate = esp_plen ? ESP_P_PAYLOAD : ESP_P_CRC_LO;
                }
                break;
            case ESP_P_PAYLOAD:
                esp_ppayload[esp_pidx++] = b;
                esp_pcrc = CRC16_Update(esp_pcrc, b);
                if (esp_pidx == esp_plen) esp_pstate = ESP_P_CRC_LO;
                break;
            case ESP_P_CRC_LO:
                esp_expected_crc = b;
                esp_pstate = ESP_P_CRC_HI;
                break;
            case ESP_P_CRC_HI:
                esp_expected_crc |= ((uint16_t)b << 8);
                if (esp_pcrc == esp_expected_crc) {
                    HandleEsp32Frame(esp_ppayload, esp_plen);
                }
                esp_pstate = ESP_P_SYNC;
                break;
            default:
                esp_pstate = ESP_P_SYNC;
                break;
        }
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart->Instance == USART1) {
        uint16_t next = (uint16_t)((uart1_head + 1U) % UART1_RING_SIZE);
        if (next != uart1_tail) {
            uart1_ring[uart1_head] = uart1_rx_single;
            uart1_head = next;
        }
        HAL_UART_Receive_IT(&huart1, &uart1_rx_single, 1);
    }
}
/* USER CODE END 0 */

int main(void)
{
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_USART1_UART_Init();
    MX_USB_DEVICE_Init();

    /* USER CODE BEGIN 2 */
    ReferenceInit();
    StreamReset();
    AlertSet(0);
    last_esp32_hb_out_ms = HAL_GetTick();
    HAL_UART_Receive_IT(&huart1, &uart1_rx_single, 1);
    /* USER CODE END 2 */

    /* USER CODE BEGIN WHILE */
    while (1)
    {
        ButtonsPoll();
        ProcessPiUSBBytes();
        ProcessEsp32UartBytes();

        uint32_t now = HAL_GetTick();

        if ((now - last_esp32_hb_out_ms) >= ESP32_HB_INTERVAL_MS) {
            last_esp32_hb_out_ms = now;
            ESP32_SendComponentHeartbeat();
        }

        HAL_Delay(1U);
    }
    /* USER CODE END WHILE */
}

void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM = 25;
    RCC_OscInitStruct.PLL.PLLN = 192;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ = 4;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) Error_Handler();

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK) Error_Handler();
}

static void MX_USART1_UART_Init(void)
{
    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK) Error_Handler();
}

static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef g = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOH_CLK_ENABLE();

    g.Pin = REGISTER_PIN | RESTORE_PIN;
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_PULLUP;
    g.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOA, &g);

    g.Pin = REBASELINE_PIN | REVOKE_PIN;
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_PULLUP;
    g.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &g);

    g.Pin = ALERT_PIN | ONBOARD_LED_PIN;
    g.Mode = GPIO_MODE_OUTPUT_PP;
    g.Pull = GPIO_NOPULL;
    g.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOC, &g);

    HAL_GPIO_WritePin(ALERT_PORT, ALERT_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(ONBOARD_LED_PORT, ONBOARD_LED_PIN, GPIO_PIN_SET);
}

void Error_Handler(void)
{
    __disable_irq();
    AlertSet(1);
    while (1) {}
}
