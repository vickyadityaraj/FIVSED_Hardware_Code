#include "reference_store.h"
#include "main.h"
#include "stm32f411_min.h"
#include <string.h>
#include <stddef.h>

#define REF_MAGIC   0x53564946UL /* "FIVS" little-endian */
#define REF_VERSION 3UL
#define REF_LEGACY_VERSION 1UL
#define REF_TABLE_ADDR FLASH_SECTOR7_ADDR
#define FLASH_ERROR_MASK ((1UL << 1) | (1UL << 4) | (1UL << 5) | (1UL << 6) | (1UL << 7) | (1UL << 8))

/* Version-1 table retained only for safe on-device migration. The old layout
   had no physical_id field. It is copied into the v3 structure with an empty
   physical_id; no reference digest is changed. */
typedef struct {
    uint8_t used;
    uint8_t jedec[3];
    uint8_t reserved0;
    uint32_t firmware_size;
    uint8_t reference[32];
    uint8_t previous[32];
    char target_id[TARGET_ID_MAX];
} reference_slot_v1_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t sequence;
    reference_slot_v1_t slots[MAX_SLOTS];
    uint32_t crc32;
} reference_table_v1_t;

static reference_table_t g_tbl;
static uint8_t g_storage_ok = 1u;

static uint32_t crc32(const uint8_t *data, uint32_t len) {
    uint32_t crc=0xFFFFFFFFUL;
    for(uint32_t i=0;i<len;i++){
        crc ^= data[i];
        for(uint32_t b=0;b<8;b++) crc=(crc&1u)?((crc>>1)^0xEDB88320UL):(crc>>1);
    }
    return ~crc;
}

static uint32_t table_crc(const reference_table_t *tbl) {
    return crc32((const uint8_t*)tbl,(uint32_t)offsetof(reference_table_t,crc32));
}

static uint32_t legacy_table_crc(const reference_table_v1_t *tbl) {
    return crc32((const uint8_t*)tbl,(uint32_t)offsetof(reference_table_v1_t,crc32));
}

static void flash_wait(void){ while(FLASH_SR & FLASH_SR_BSY){} }
static void flash_unlock(void){
    if(FLASH_CR & FLASH_CR_LOCK){ FLASH_KEYR=0x45670123UL; FLASH_KEYR=0xCDEF89ABUL; }
}
static void flash_lock(void){ FLASH_CR |= FLASH_CR_LOCK; }

static int flash_save(void){
    g_tbl.magic=REF_MAGIC;
    g_tbl.version=REF_VERSION;
    g_tbl.sequence++;
    g_tbl.crc32=table_crc(&g_tbl);

    flash_unlock();
    flash_wait();
    FLASH_SR = FLASH_SR_EOP | FLASH_ERROR_MASK;
    FLASH_CR = FLASH_CR_SER | FLASH_CR_PSIZE_WORD | (7UL<<FLASH_CR_SNB_SHIFT);
    FLASH_CR |= FLASH_CR_STRT;
    flash_wait();
    if(FLASH_SR & FLASH_ERROR_MASK){ flash_lock(); return -1; }
    FLASH_SR = FLASH_SR_EOP;
    FLASH_CR &= ~FLASH_CR_SER;
    FLASH_CR |= FLASH_CR_PSIZE_WORD | FLASH_CR_PG;

    const uint32_t *src=(const uint32_t*)&g_tbl;
    const uint32_t words=(uint32_t)(sizeof(g_tbl)/4u);
    if((sizeof(g_tbl)%4u)!=0u){ FLASH_CR &= ~FLASH_CR_PG; flash_lock(); return -2; }
    for(uint32_t i=0;i<words;i++){
        *(volatile uint32_t*)(REF_TABLE_ADDR+i*4u)=src[i];
        flash_wait();
        if((FLASH_SR & FLASH_ERROR_MASK)!=0){
            FLASH_CR &= ~FLASH_CR_PG;
            flash_lock();
            return -3;
        }
        FLASH_SR=FLASH_SR_EOP;
    }
    FLASH_CR &= ~FLASH_CR_PG;
    flash_lock();
    if(memcmp((const void*)REF_TABLE_ADDR,&g_tbl,sizeof(g_tbl))!=0)return -4;
    return 0;
}

void reference_init(void){
    const reference_table_t *stored=(const reference_table_t*)REF_TABLE_ADDR;
    const uint8_t *raw=(const uint8_t*)stored;
    int erased=1;
    for(uint32_t i=0;i<sizeof(reference_table_t);i++){
        if(raw[i]!=0xFFu){erased=0;break;}
    }

    if(stored->magic==REF_MAGIC && stored->version==REF_VERSION && stored->crc32==table_crc(stored)){
        memcpy(&g_tbl,stored,sizeof(g_tbl));
        g_storage_ok=1u;
        return;
    }

    /* Safe migration path for the previously shipped v1 table. */
    const reference_table_v1_t *legacy=(const reference_table_v1_t*)REF_TABLE_ADDR;
    if(legacy->magic==REF_MAGIC && legacy->version==REF_LEGACY_VERSION &&
       legacy->crc32==legacy_table_crc(legacy)){
        memset(&g_tbl,0,sizeof(g_tbl));
        g_tbl.magic=REF_MAGIC;
        g_tbl.version=REF_VERSION;
        g_tbl.sequence=legacy->sequence;
        for(uint8_t s=0;s<MAX_SLOTS;s++){
            g_tbl.slots[s].used=legacy->slots[s].used;
            memcpy(g_tbl.slots[s].jedec,legacy->slots[s].jedec,3);
            g_tbl.slots[s].reserved0=legacy->slots[s].reserved0;
            g_tbl.slots[s].firmware_size=legacy->slots[s].firmware_size;
            memcpy(g_tbl.slots[s].reference,legacy->slots[s].reference,32);
            memcpy(g_tbl.slots[s].previous,legacy->slots[s].previous,32);
            memcpy(g_tbl.slots[s].target_id,legacy->slots[s].target_id,TARGET_ID_MAX);
            g_tbl.slots[s].physical_id[0]='\0';
        }
        g_tbl.crc32=table_crc(&g_tbl);
        g_storage_ok=1u;
        return;
    }

    if(erased){
        memset(&g_tbl,0,sizeof(g_tbl));
        g_tbl.magic=REF_MAGIC;
        g_tbl.version=REF_VERSION;
        g_tbl.sequence=0u;
        g_tbl.crc32=table_crc(&g_tbl);
        g_storage_ok=1u;
    }else{
        /* Never silently trust an unknown/corrupt table. */
        memset(&g_tbl,0,sizeof(g_tbl));
        g_storage_ok=0u;
    }
}

int reference_storage_ok(void){ return g_storage_ok != 0u; }
int reference_is_valid(uint8_t slot){ return slot<MAX_SLOTS && g_tbl.slots[slot].used; }
const reference_slot_t *reference_get(uint8_t slot){ return slot<MAX_SLOTS ? &g_tbl.slots[slot] : 0; }

int reference_register(uint8_t slot, const uint8_t digest[32], uint32_t size,
                       const uint8_t jedec[3], const char *target_id,
                       const char *physical_id){
    if(!g_storage_ok || slot>=MAX_SLOTS || g_tbl.slots[slot].used || !digest || !jedec || !target_id || !target_id[0]) return -1;
    memset(&g_tbl.slots[slot],0,sizeof(g_tbl.slots[slot]));
    g_tbl.slots[slot].used=1u;
    memcpy(g_tbl.slots[slot].jedec,jedec,3);
    g_tbl.slots[slot].firmware_size=size;
    memcpy(g_tbl.slots[slot].reference,digest,32);
    memcpy(g_tbl.slots[slot].previous,digest,32);
    strncpy(g_tbl.slots[slot].target_id,target_id,TARGET_ID_MAX-1u);
    g_tbl.slots[slot].target_id[TARGET_ID_MAX-1u]='\0';
    if(physical_id){
        strncpy(g_tbl.slots[slot].physical_id,physical_id,PHYSICAL_ID_MAX-1u);
        g_tbl.slots[slot].physical_id[PHYSICAL_ID_MAX-1u]='\0';
    }
    const int rc=flash_save();
    if(rc!=0)g_storage_ok=0u;
    return rc;
}

int reference_update(uint8_t slot, const uint8_t digest[32], uint32_t size,
                     const char *physical_id){
    if(!g_storage_ok || slot>=MAX_SLOTS || !g_tbl.slots[slot].used || !digest) return -1;
    memcpy(g_tbl.slots[slot].previous,g_tbl.slots[slot].reference,32);
    memcpy(g_tbl.slots[slot].reference,digest,32);
    g_tbl.slots[slot].firmware_size=size;
    if(physical_id && physical_id[0]){
        strncpy(g_tbl.slots[slot].physical_id,physical_id,PHYSICAL_ID_MAX-1u);
        g_tbl.slots[slot].physical_id[PHYSICAL_ID_MAX-1u]='\0';
    }
    const int rc=flash_save();
    if(rc!=0)g_storage_ok=0u;
    return rc;
}

int reference_revoke(uint8_t slot){
    if(!g_storage_ok || slot>=MAX_SLOTS || !g_tbl.slots[slot].used) return -1;
    memset(&g_tbl.slots[slot],0,sizeof(g_tbl.slots[slot]));
    const int rc=flash_save();
    if(rc!=0)g_storage_ok=0u;
    return rc;
}

int reference_restore(uint8_t slot){
    if(!g_storage_ok || slot>=MAX_SLOTS || !g_tbl.slots[slot].used) return -1;
    uint8_t tmp[32];
    memcpy(tmp,g_tbl.slots[slot].reference,32);
    memcpy(g_tbl.slots[slot].reference,g_tbl.slots[slot].previous,32);
    memcpy(g_tbl.slots[slot].previous,tmp,32);
    memset(tmp,0,sizeof(tmp));
    const int rc=flash_save();
    if(rc!=0)g_storage_ok=0u;
    return rc;
}
