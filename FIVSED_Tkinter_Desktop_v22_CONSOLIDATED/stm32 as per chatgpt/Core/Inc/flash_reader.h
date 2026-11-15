#ifndef FIVSED_FLASH_READER_H
#define FIVSED_FLASH_READER_H
#include <stdint.h>

typedef struct {
    uint8_t jedec[3];
    uint32_t size_bytes;
    uint8_t present;
    uint8_t supported;
} flash_info_t;

int flash_probe(uint8_t slot, flash_info_t *info);
int flash_hash(uint8_t slot, uint8_t digest[32], uint32_t *size_bytes, uint8_t *all_ff, uint32_t request_id);

#endif
