#ifndef FIVSED_REFERENCE_STORE_H
#define FIVSED_REFERENCE_STORE_H
#include <stdint.h>

#define MAX_SLOTS 4
#define TARGET_ID_MAX 32
#define PHYSICAL_ID_MAX 32

/* The logical target ID is an operator-facing identity (for example the
   embedded SERIAL). It is never a trusted hash. physical_id retains the
   W25Q64 factory UID supplied by the acquisition path. */
typedef struct {
    uint8_t used;
    uint8_t jedec[3];
    uint8_t reserved0;
    uint32_t firmware_size;
    uint8_t reference[32];
    uint8_t previous[32];
    char target_id[TARGET_ID_MAX];
    char physical_id[PHYSICAL_ID_MAX];
} reference_slot_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t sequence;
    reference_slot_t slots[MAX_SLOTS];
    uint32_t crc32;
} reference_table_t;

void reference_init(void);
int reference_storage_ok(void);
int reference_is_valid(uint8_t slot);
const reference_slot_t *reference_get(uint8_t slot);
int reference_register(uint8_t slot, const uint8_t digest[32], uint32_t size,
                       const uint8_t jedec[3], const char *target_id,
                       const char *physical_id);
int reference_update(uint8_t slot, const uint8_t digest[32], uint32_t size,
                     const char *physical_id);
int reference_revoke(uint8_t slot);
int reference_restore(uint8_t slot);

#endif
