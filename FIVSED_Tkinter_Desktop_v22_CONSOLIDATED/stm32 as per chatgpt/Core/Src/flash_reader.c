#include "flash_reader.h"
#include "main.h"
#include "reference_store.h"
#include "platform.h"
#include "sha256_engine.h"
#include "protocol.h"
#include "stm32f411_min.h"
#include <string.h>

#define CMD_JEDEC 0x9Fu
#define CMD_READ  0x03u
#define CHUNK     256u
#define SPI_TIMEOUT_MS 20u

static const uint32_t cs_bases[MAX_SLOTS]={GPIOA,GPIOB,GPIOB,GPIOB};
static const uint8_t  cs_pins [MAX_SLOTS]={4u,0u,1u,2u};

static void cs_low(uint8_t slot){ GPIO_BSRR(cs_bases[slot])=(1UL<<(cs_pins[slot]+16u)); }
static void cs_high(uint8_t slot){ GPIO_BSRR(cs_bases[slot])=(1UL<<cs_pins[slot]); }

static int spi_wait_txe(uint32_t timeout){ uint32_t start=fivsed_millis(); while(!(SPI1_SR&SPI_SR_TXE)){if(fivsed_millis()-start>=timeout)return -1;}return 0; }
static int spi_wait_rxne(uint32_t timeout){ uint32_t start=fivsed_millis(); while(!(SPI1_SR&SPI_SR_RXNE)){if(fivsed_millis()-start>=timeout)return -1;}return 0; }
static int spi_wait_not_busy(uint32_t timeout){ uint32_t start=fivsed_millis(); while(SPI1_SR&SPI_SR_BSY){if(fivsed_millis()-start>=timeout)return -1;}return 0; }
static int spi_xfer(uint8_t v, uint8_t *rx){
    if(spi_wait_txe(SPI_TIMEOUT_MS)!=0)return -1;
    SPI1_DR=v;
    if(spi_wait_rxne(SPI_TIMEOUT_MS)!=0)return -2;
    if(rx)*rx=(uint8_t)SPI1_DR; else (void)SPI1_DR;
    return 0;
}

static uint32_t capacity_from_jedec(uint8_t cap){
    if(cap<16u || cap>28u) return 0;
    return 1UL << cap;
}

int flash_probe(uint8_t slot, flash_info_t *info){
    if(!info || slot>=MAX_SLOTS) return -1;
    memset(info,0,sizeof(*info));
    cs_low(slot);
    uint8_t cmd=CMD_JEDEC;
    uint8_t rx=0;
    if(spi_xfer(cmd,&rx)!=0){cs_high(slot);return -2;}
    if(spi_xfer(0xFFu,&info->jedec[0])!=0 || spi_xfer(0xFFu,&info->jedec[1])!=0 || spi_xfer(0xFFu,&info->jedec[2])!=0){cs_high(slot);return -2;}
    if(spi_wait_not_busy(SPI_TIMEOUT_MS)!=0){cs_high(slot);return -2;}
    cs_high(slot);
    if((info->jedec[0]==0u&&info->jedec[1]==0u&&info->jedec[2]==0u) || (info->jedec[0]==0xFFu&&info->jedec[1]==0xFFu&&info->jedec[2]==0xFFu)) return 0;
    info->present=1u;
    info->size_bytes=capacity_from_jedec(info->jedec[2]);
    info->supported=(info->jedec[0]==0xEFu && info->jedec[1]==0x40u && info->size_bytes>0u && info->size_bytes<=FLASH_MAX_FW_BYTES);
    return 1;
}

int flash_hash(uint8_t slot,uint8_t digest[32],uint32_t *size_bytes,uint8_t *all_ff,uint32_t request_id){
    flash_info_t info;
    int probe=flash_probe(slot,&info);
    if(probe<=0) return -1;
    if(!info.supported) return -2;
    if(info.size_bytes==0 || info.size_bytes>FLASH_MAX_FW_BYTES) return -2;

    static uint8_t buf[CHUNK];
    sha256_ctx_t ctx; sha256_init(&ctx);
    uint32_t non_ff=0;
    uint32_t processed=0;
    uint8_t cmd[4]={CMD_READ,0,0,0};

    cs_low(slot);
    for(int i=0;i<4;i++){
        if(spi_xfer(cmd[i],NULL)!=0){cs_high(slot);return -1;}
    }

    while(processed<info.size_bytes){
        uint32_t remaining=info.size_bytes-processed;
        uint32_t take=remaining>CHUNK?CHUNK:remaining;
        for(uint32_t i=0;i<take;i++){
            if(spi_xfer(0xFFu,&buf[i])!=0){
                cs_high(slot);
                if(size_bytes)*size_bytes=processed;
                return -1;
            }
            if(buf[i]!=0xFFu) non_ff++;
        }
        sha256_update(&ctx,buf,take); processed+=take;
        if((processed%(32u*1024u))==0u || processed==info.size_bytes){
            protocol_send_progress(request_id,(uint16_t)(processed/CHUNK),"STM32_CALCULATING_SHA256",processed,info.size_bytes);
            protocol_tick();
        }
    }
    if(spi_wait_not_busy(SPI_TIMEOUT_MS)!=0){cs_high(slot);if(size_bytes)*size_bytes=processed;return -1;}
    cs_high(slot);
    if(non_ff==0u) return -3;
    sha256_final(&ctx,digest);
    if(size_bytes)*size_bytes=info.size_bytes;
    if(all_ff)*all_ff=0u;
    return 0;
}
