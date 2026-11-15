#ifndef FIVSED_SHA256_ENGINE_H
#define FIVSED_SHA256_ENGINE_H
#include <stdint.h>

typedef struct {
    uint32_t state[8];
    uint64_t total_len;
    uint32_t buffer_len;
    uint8_t buffer[64];
} sha256_ctx_t;

void sha256_init(sha256_ctx_t *ctx);
void sha256_update(sha256_ctx_t *ctx, const uint8_t *data, uint32_t len);
void sha256_final(sha256_ctx_t *ctx, uint8_t out[32]);
void sha256_hmac(const uint8_t *key, uint32_t key_len, const uint8_t *msg, uint32_t msg_len, uint8_t out[32]);

#endif
