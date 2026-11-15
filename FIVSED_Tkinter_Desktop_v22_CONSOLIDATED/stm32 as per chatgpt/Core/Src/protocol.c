#include "protocol.h"
#include "buttons.h"
#include "flash_reader.h"
#include "reference_store.h"
#include "platform.h"
#include "sha256_engine.h"
#include "main.h"
#include "stm32f411_min.h"
#include "usb_transport.h"
#include <stdio.h>
#include <string.h>

#define RX_BYTE_TIMEOUT_MS 50u
#define HMAC_KEY_LEN 32u
#define STREAM_MAX_BYTES FLASH_MAX_FW_BYTES
#define PI_HEARTBEAT_TIMEOUT_MS 45000u
#define ESP32_HEARTBEAT_INTERVAL_MS 5000u
#define ESP32_HEARTBEAT_TIMEOUT_MS 15000u
#define ESP32_RX_SYNC 0x5Au
#define ESP32_RX_MAX_PAYLOAD 256u

typedef enum {
    ESP_RX_WAIT_SYNC = 0,
    ESP_RX_WAIT_VERSION,
    ESP_RX_LEN_LO,
    ESP_RX_LEN_HI,
    ESP_RX_PAYLOAD,
    ESP_RX_CRC_LO,
    ESP_RX_CRC_HI
} esp_rx_state_t;

/* This key never leaves STM32. ESP32 only transports the signed message. */
static const uint8_t FIVSED_HMAC_KEY[HMAC_KEY_LEN] = {
    0x79,0xC2,0x51,0x18,0xA7,0x2F,0x4D,0x9B,0xE3,0x11,0x63,0x8A,0xD4,0x20,0x5E,0xF1,
    0x42,0xB7,0x05,0xC8,0x33,0x6D,0x90,0x1A,0xEE,0x48,0x7C,0x14,0xD9,0x62,0xAF,0x30
};

typedef struct {
    uint8_t active;
    uint32_t request_id;
    uint8_t slot;
    uint16_t next_sequence;
    uint32_t total_bytes;
    uint32_t processed_bytes;
    uint32_t start_ms;
    uint8_t non_ff_seen;
    char target_id[PROTO_TARGET_ID_MAX];
    char physical_id[PHYSICAL_ID_MAX];
    sha256_ctx_t sha;
} stream_state_t;

typedef struct {
    esp_rx_state_t state;
    uint8_t version;
    uint16_t length;
    uint16_t position;
    uint8_t payload[ESP32_RX_MAX_PAYLOAD];
    uint8_t crc_lo;
} esp_rx_parser_t;

static stream_state_t g_stream;
static esp_rx_parser_t g_esp_rx;
static uint32_t g_pi_last_seen_ms;
static uint32_t g_esp32_last_seen_ms;
static uint32_t g_last_heartbeat_ms;
static uint32_t g_heartbeat_sequence;
static uint16_t g_esp32_rx_crc_expected;

static uint16_t crc16_ccitt(const uint8_t *data, uint32_t len){
    uint16_t crc=0xFFFFu;
    for(uint32_t i=0;i<len;i++){
        crc^=(uint16_t)data[i]<<8;
        for(int b=0;b<8;b++)crc=(crc&0x8000u)?(uint16_t)((crc<<1)^0x1021u):(uint16_t)(crc<<1);
    }
    return crc;
}

static int json_slot_value(const char *json,const char *key,uint8_t default_value){
    const char *p=strstr(json,key);
    if(!p)return default_value;
    p=strchr(p,':');
    if(!p)return default_value;
    while(*++p==' ' || *p=='\t'){}
    if(*p<'0' || *p>'9')return default_value;
    return (uint8_t)(*p-'0');
}

static int json_u32_value(const char *json,const char *key,uint32_t *out){
    const char *p=strstr(json,key);
    if(!p || !out)return 0;
    p=strchr(p,':');
    if(!p)return 0;
    while(*++p==' ' || *p=='\t'){}
    uint32_t value=0; uint8_t digits=0;
    while(*p>='0' && *p<='9'){
        value=value*10u+(uint32_t)(*p-'0');
        p++; digits=1;
    }
    if(!digits)return 0;
    *out=value;
    return 1;
}

static int json_string_value(const char *json,const char *key,char *out,uint32_t out_len){
    const char *p=strstr(json,key);
    if(!p || !out || out_len<2u)return 0;
    p=strchr(p,':');
    if(!p)return 0;
    p++;
    while(*p==' ' || *p=='\t')p++;
    if(*p!='"')return 0;
    p++;
    uint32_t i=0;
    while(*p && *p!='"'){
        if(i+1u>=out_len)return 0;
        if(*p=='\\')return 0;
        out[i++]=*p++;
    }
    if(*p!='"')return 0;
    out[i]='\0';
    return i>0u;
}

static void protocol_send_simple(uint8_t type,uint32_t rid,uint16_t seq,const char *msg){
    protocol_send(type,rid,seq,(const uint8_t*)msg,(uint16_t)strlen(msg));
}

static void slot_target_id(uint8_t slot,const uint8_t jedec[3],char out[PROTO_TARGET_ID_MAX]){
    snprintf(out,PROTO_TARGET_ID_MAX,"spi-slot-%u-%02x%02x%02x",(unsigned)(slot+1u),jedec[0],jedec[1],jedec[2]);
}

static uint8_t esp32_is_active(void){
    const uint32_t now=fivsed_millis();
    return (g_esp32_last_seen_ms!=0u && (uint32_t)(now-g_esp32_last_seen_ms)<=ESP32_HEARTBEAT_TIMEOUT_MS) ? 1u : 0u;
}

void protocol_init(void){
    memset(&g_stream,0,sizeof(g_stream));
    memset(&g_esp_rx,0,sizeof(g_esp_rx));
    g_esp_rx.state=ESP_RX_WAIT_SYNC;
    g_pi_last_seen_ms=0u;
    g_esp32_last_seen_ms=0u;
    g_last_heartbeat_ms=(uint32_t)(fivsed_millis()-ESP32_HEARTBEAT_INTERVAL_MS);
    g_heartbeat_sequence=0u;
}

void protocol_send(uint8_t type,uint32_t request_id,uint16_t sequence,const uint8_t *payload,uint16_t len){
    if(len>PROTO_MAX_PAYLOAD)return;
    uint8_t buf[PROTO_MAX_PAYLOAD+15u];
    uint32_t pos=0;
    buf[pos++]=FIVSED_SYNC; buf[pos++]=FIVSED_VERSION; buf[pos++]=type; buf[pos++]=0; buf[pos++]=0;
    buf[pos++]=(uint8_t)request_id;buf[pos++]=(uint8_t)(request_id>>8);buf[pos++]=(uint8_t)(request_id>>16);buf[pos++]=(uint8_t)(request_id>>24);
    buf[pos++]=(uint8_t)sequence;buf[pos++]=(uint8_t)(sequence>>8);
    buf[pos++]=(uint8_t)len;buf[pos++]=(uint8_t)(len>>8);
    if(len){memcpy(buf+pos,payload,len);pos+=len;}
    uint16_t crc=crc16_ccitt(buf+1,pos-1);buf[pos++]=(uint8_t)crc;buf[pos++]=(uint8_t)(crc>>8);
    fivsed_usb_write(buf,(uint16_t)pos);
}

static int esp32_send_signed(const uint8_t *payload,uint16_t len){
    if(!payload || len==0u)return 0;
    uint8_t mac[32];
    sha256_hmac(FIVSED_HMAC_KEY,HMAC_KEY_LEN,payload,len,mac);
    if(!esp32_uart_write_byte(0xA5u,100u) ||
       !esp32_uart_write_byte((uint8_t)len,100u) ||
       !esp32_uart_write_byte((uint8_t)(len>>8),100u)) return 0;
    for(uint16_t i=0;i<len;i++){
        if(!esp32_uart_write_byte(payload[i],100u))return 0;
    }
    for(uint8_t i=0;i<32u;i++){
        if(!esp32_uart_write_byte(mac[i],100u))return 0;
    }
    return esp32_uart_tx_flush(200u);
}

static void esp32_send_heartbeat_ack(void){
    char json[220];
    const int n=snprintf(json,sizeof(json),
        "{\"version\":1,\"event\":\"ESP32_HEARTBEAT_ACK\",\"source\":\"STM32\",\"status\":\"ACK\",\"message\":\"ACK: ESP32_ACTIVE\",\"stm32_active\":true,\"sequence\":%lu}",
        (unsigned long)(++g_heartbeat_sequence));
    if(n>0 && n<(int)sizeof(json)){
        (void)esp32_send_signed((const uint8_t*)json,(uint16_t)n);
    }
}

static void esp32_send_component_heartbeat(void){
    const uint32_t now=fivsed_millis();
    const uint8_t pi_active=(g_pi_last_seen_ms!=0u && (uint32_t)(now-g_pi_last_seen_ms)<=PI_HEARTBEAT_TIMEOUT_MS) ? 1u : 0u;
    const uint8_t esp_active=esp32_is_active();
    char json[360];
    const int n=snprintf(json,sizeof(json),
        "{\"version\":1,\"event\":\"COMPONENT_HEARTBEAT\",\"source\":\"STM32\",\"status\":\"ACTIVE\",\"stm32_active\":true,\"raspberry_pi_active\":%s,\"esp32_active\":%s,\"stm32_uptime_ms\":%lu,\"pi_last_seen_ms\":%lu,\"esp32_last_seen_ms\":%lu,\"sequence\":%lu}",
        pi_active?"true":"false",esp_active?"true":"false",
        (unsigned long)now,(unsigned long)g_pi_last_seen_ms,(unsigned long)g_esp32_last_seen_ms,
        (unsigned long)(++g_heartbeat_sequence));
    if(n>0 && n<(int)sizeof(json)){
        (void)esp32_send_signed((const uint8_t*)json,(uint16_t)n);
    }
}

/* ESP32 -> STM32 reverse-control framing:
   0x5A | version(1) | length LE(2) | JSON | CRC16 LE
   CRC16 is calculated over version + length bytes + JSON. */
static void esp32_rx_reset(void){
    memset(&g_esp_rx,0,sizeof(g_esp_rx));
    g_esp_rx.state=ESP_RX_WAIT_SYNC;
}

static void esp32_process_control_frame(void){
    if(g_esp_rx.version!=FIVSED_VERSION || g_esp_rx.length==0u || g_esp_rx.length>ESP32_RX_MAX_PAYLOAD)return;
    uint8_t crcbuf[ESP32_RX_MAX_PAYLOAD+3u];
    crcbuf[0]=g_esp_rx.version;
    crcbuf[1]=(uint8_t)g_esp_rx.length;
    crcbuf[2]=(uint8_t)(g_esp_rx.length>>8);
    memcpy(crcbuf+3,g_esp_rx.payload,g_esp_rx.length);
    const uint16_t actual=crc16_ccitt(crcbuf,(uint32_t)g_esp_rx.length+3u);
    if(actual!=g_esp32_rx_crc_expected){
        return;
    }

    char json[ESP32_RX_MAX_PAYLOAD+1u];
    memcpy(json,g_esp_rx.payload,g_esp_rx.length);
    json[g_esp_rx.length]='\0';

    char event[48];
    if(!json_string_value(json,"\"event\"",event,sizeof(event)))return;
    if(strcmp(event,"ESP32_HEARTBEAT")!=0)return;

    g_esp32_last_seen_ms=fivsed_millis();
    esp32_send_heartbeat_ack();
}


static void esp32_rx_poll(void){
    uint8_t byte;
    while(1){
        const int rc=esp32_uart_read_byte(&byte);
        if(rc<=0)break;
        switch(g_esp_rx.state){
            case ESP_RX_WAIT_SYNC:
                if(byte==ESP32_RX_SYNC)g_esp_rx.state=ESP_RX_WAIT_VERSION;
                break;
            case ESP_RX_WAIT_VERSION:
                g_esp_rx.version=byte;
                if(byte!=FIVSED_VERSION){esp32_rx_reset();}
                else g_esp_rx.state=ESP_RX_LEN_LO;
                break;
            case ESP_RX_LEN_LO:
                g_esp_rx.length=byte;
                g_esp_rx.state=ESP_RX_LEN_HI;
                break;
            case ESP_RX_LEN_HI:
                g_esp_rx.length|=(uint16_t)byte<<8;
                if(g_esp_rx.length==0u || g_esp_rx.length>ESP32_RX_MAX_PAYLOAD){esp32_rx_reset();}
                else {g_esp_rx.position=0u;g_esp_rx.state=ESP_RX_PAYLOAD;}
                break;
            case ESP_RX_PAYLOAD:
                g_esp_rx.payload[g_esp_rx.position++]=byte;
                if(g_esp_rx.position>=g_esp_rx.length)g_esp_rx.state=ESP_RX_CRC_LO;
                break;
            case ESP_RX_CRC_LO:
                g_esp_rx.crc_lo=byte;
                g_esp_rx.state=ESP_RX_CRC_HI;
                break;
            case ESP_RX_CRC_HI:
                g_esp32_rx_crc_expected=(uint16_t)g_esp_rx.crc_lo | ((uint16_t)byte<<8);
                esp32_process_control_frame();
                esp32_rx_reset();
                break;
            default:
                esp32_rx_reset();
                break;
        }
    }
}

void protocol_tick(void){
    const uint32_t now=fivsed_millis();
    esp32_rx_poll();
    if((uint32_t)(now-g_last_heartbeat_ms)>=ESP32_HEARTBEAT_INTERVAL_MS){
        g_last_heartbeat_ms=now;
        esp32_send_component_heartbeat();
    }
}

void protocol_send_progress(uint32_t request_id,uint16_t sequence,const char *stage,uint32_t done,uint32_t total){
    char json[220];
    const int n=snprintf(json,sizeof(json),"{\"stage\":\"%s\",\"bytes_processed\":%lu,\"total_bytes\":%lu}",stage,(unsigned long)done,(unsigned long)total);
    if(n<0 || n>=(int)sizeof(json))return;
    protocol_send(MSG_SCAN_PROGRESS,request_id,sequence,(const uint8_t*)json,(uint16_t)n);
}

void protocol_send_result(uint32_t request_id,uint8_t slot,const char *result,const char *reason,
                          uint32_t firmware_size,uint32_t duration_ms){
    /* Digest and trusted reference never leave the STM32. Add the web-layer
       status field for compatibility, but keep the integrity result itself
       authoritative and signed by STM32 before ESP32 forwarding. */
    const char *status=(result && (strcmp(result,"MATCH")==0 || strcmp(result,"NEW_TARGET_REGISTERED")==0 || strcmp(result,"REFERENCE_UPDATED")==0))?"PASS":"FAIL";
    char final[640];
    const int n=snprintf(final,sizeof(final),
        "{\"version\":1,\"event\":\"FIRMWARE_VERIFICATION\",\"source\":\"STM32\",\"decision_authority\":\"STM32\",\"verification_id\":%lu,\"scan_id\":%lu,\"slot\":%u,\"result\":\"%s\",\"status\":\"%s\",\"firmware_size\":%lu,\"duration_ms\":%lu,\"reason\":\"%s\",\"hash_disclosure\":false}",
        (unsigned long)request_id,(unsigned long)request_id,(unsigned)slot,result,status,(unsigned long)firmware_size,
        (unsigned long)duration_ms,reason?reason:"");
    if(n<0 || n>=(int)sizeof(final))return;
    protocol_send(MSG_SCAN_RESULT,request_id,0,(const uint8_t*)final,(uint16_t)n);
    (void)esp32_send_signed((const uint8_t*)final,(uint16_t)n);
}

static void send_hello(uint32_t rid){
    const char *json="{\"protocol\":1,\"controller\":\"STM32F411CEU6\",\"role\":\"SECURITY_AUTHORITY\",\"esp32_uart\":\"115200_8N1_BIDIRECTIONAL\"}";
    protocol_send(MSG_HELLO_RESP,rid,0,(const uint8_t*)json,(uint16_t)strlen(json));
}

static void send_status(uint32_t rid){
    char json[PROTO_MAX_PAYLOAD];
    size_t pos=0u;
    int n=snprintf(json+pos,sizeof(json)-pos,"{\"controller\":\"STM32F411CEU6\",\"esp32_active\":%s,\"pi_active\":%s,\"slots\":[",
        esp32_is_active()?"true":"false",
        (g_pi_last_seen_ms!=0u && (uint32_t)(fivsed_millis()-g_pi_last_seen_ms)<=PI_HEARTBEAT_TIMEOUT_MS)?"true":"false");
    if(n<0 || (size_t)n>=sizeof(json)-pos)return;
    pos+=(size_t)n;
    uint8_t emitted=0u;

    for(uint8_t s=0;s<MAX_SLOTS;s++){
        flash_info_t info;
        memset(&info,0,sizeof(info));
        const int pr=flash_probe(s,&info);
        const uint8_t connected=(pr>0 && info.present) ? 1u : 0u;
        const reference_slot_t *ref=reference_get(s);
        const uint8_t registered=(ref && ref->used) ? 1u : 0u;

        if(!connected && !registered)continue;

        char direct_tid[PROTO_TARGET_ID_MAX]={0};
        char tid[PROTO_TARGET_ID_MAX]={0};
        if(connected)slot_target_id(s,info.jedec,direct_tid);
        if(registered)strncpy(tid,ref->target_id,TARGET_ID_MAX-1u);
        else strncpy(tid,direct_tid,TARGET_ID_MAX-1u);
        tid[TARGET_ID_MAX-1u]='\0';

        const uint8_t jedec[3]={
            connected?info.jedec[0]:(registered?ref->jedec[0]:0u),
            connected?info.jedec[1]:(registered?ref->jedec[1]:0u),
            connected?info.jedec[2]:(registered?ref->jedec[2]:0u)
        };
        const uint32_t fw_size=connected?info.size_bytes:(registered?ref->firmware_size:0u);
        const char *model=(jedec[0]==0xEFu && jedec[1]==0x40u && jedec[2]==0x17u)?"W25Q64JV":"SPI NOR";
        const char *man=(jedec[0]==0xEFu)?"Winbond":"N/A";

        if(emitted){
            n=snprintf(json+pos,sizeof(json)-pos,",");
            if(n<0 || (size_t)n>=sizeof(json)-pos)return;
            pos+=(size_t)n;
        }

        n=snprintf(json+pos,sizeof(json)-pos,
            "{\"slot\":%u,\"connected\":%s,\"registered\":%s,\"target_id\":\"%s\",\"physical_id\":\"%s\",\"manufacturer\":\"%s\",\"model\":\"%s\",\"type\":\"SPI_NOR\",\"jedec\":\"%02x%02x%02x\",\"firmware_size\":%lu,\"acquisition_method\":\"%s\",\"capability\":\"%s\",\"firmware_access\":\"%s\"}",
            (unsigned)s,connected?"true":"false",registered?"true":"false",tid,
            registered?ref->physical_id:"",
            man,model,jedec[0],jedec[1],jedec[2],(unsigned long)fw_size,
            connected?"STM32_SPI_DIRECT":"RPI_W25Q64_SPI",
            connected?"ACQUISITION_SUPPORTED":"REFERENCE_STORED",
            connected?"READABLE":"NOT_CONNECTED");
        if(n<0 || (size_t)n>=sizeof(json)-pos)return;
        pos+=(size_t)n;
        emitted=1u;
    }

    n=snprintf(json+pos,sizeof(json)-pos,"]}");
    if(n<0 || (size_t)n>=sizeof(json)-pos)return;
    pos+=(size_t)n;
    protocol_send(MSG_STATUS_RESP,rid,0,(const uint8_t*)json,(uint16_t)pos);
}

static void drive_alert(uint8_t mismatch_or_error){
    if(mismatch_or_error){
        GPIO_BSRR(GPIOC)=(1UL<<13);
        GPIO_BSRR(GPIOC)=(1UL<<14);
    }else{
        GPIO_BSRR(GPIOC)=(1UL<<(13+16));
        GPIO_BSRR(GPIOC)=(1UL<<(14+16));
    }
}

static void handle_digest_result(uint32_t rid,uint8_t slot,const char *target_id,const char *physical_id,
                                 const uint8_t digest[32],uint32_t size,uint32_t duration_ms,const uint8_t jedec[3]){
    if(!reference_storage_ok()){
        protocol_send_result(rid,slot,"READ_ERROR","STM32 reference table is invalid; physical service is required",size,duration_ms);
        drive_alert(1); return;
    }

    const reference_slot_t *ref=reference_get(slot);
    if(ref && ref->used && strcmp(ref->target_id,target_id)!=0){
        protocol_send_result(rid,slot,"READ_ERROR","STM32 slot identity does not match the selected logical target",size,duration_ms);
        drive_alert(1); return;
    }

    if(!reference_is_valid(slot)){
        if(provisioning_register_armed()){
            if(reference_register(slot,digest,size,jedec,target_id,physical_id)==0){
                provisioning_clear_register();
                protocol_send_result(rid,slot,"NEW_TARGET_REGISTERED","Trusted reference created by physical STM32 REGISTER action",size,duration_ms);
                drive_alert(0); return;
            }
            protocol_send_result(rid,slot,"READ_ERROR","STM32 reference storage write failed",size,duration_ms);
            drive_alert(1); return;
        }
        protocol_send_result(rid,slot,"UNREGISTERED","Target measured successfully but has no trusted reference; use the physical STM32 REGISTER control to provision it",size,duration_ms);
        drive_alert(1); return;
    }

    if(provisioning_reference_update_armed()){
        if(reference_update(slot,digest,size,physical_id)==0){
            provisioning_clear_reference_update();
            protocol_send_result(rid,slot,"REFERENCE_UPDATED","Trusted reference updated by physical STM32 provisioning action",size,duration_ms);
            drive_alert(0); return;
        }
        protocol_send_result(rid,slot,"READ_ERROR","STM32 reference storage write failed",size,duration_ms);
        drive_alert(1); return;
    }

    protocol_send_progress(rid,0,"VERIFYING_REFERENCE",size,size);
    const uint8_t equal=(memcmp(digest,ref->reference,32)==0) ? 1u : 0u;
    if(equal){
        protocol_send_result(rid,slot,"MATCH","Firmware measurement matches STM32 trusted reference",size,duration_ms);
        drive_alert(0);
    }else{
        protocol_send_result(rid,slot,"HASH_MISMATCH","Firmware measurement differs from STM32 trusted reference",size,duration_ms);
        drive_alert(1);
    }
}

static void handle_scan(uint32_t rid,uint8_t slot){
    const uint32_t start=fivsed_millis();
    uint8_t digest[32]; uint32_t size=0u; uint8_t all_ff=0u;
    flash_info_t info; const int probe=flash_probe(slot,&info);
    if(probe<=0){
        protocol_send_result(rid,slot,"READ_ERROR",probe==0?"Target disconnected":"SPI transaction failed",0u,fivsed_millis()-start);
        drive_alert(1); return;
    }
    if(!info.supported){
        protocol_send_result(rid,slot,"FIRMWARE_READ_UNSUPPORTED","Connected SPI device is not a supported Winbond W25Q-family target",0u,fivsed_millis()-start);
        drive_alert(1); return;
    }
    protocol_send_progress(rid,0,"ACQUIRING_FIRMWARE",0u,info.size_bytes);
    const int rc=flash_hash(slot,digest,&size,&all_ff,rid);
    if(rc==-3){
        protocol_send_result(rid,slot,"READ_ERROR","Firmware image is all 0xFF; no readable firmware content was acquired",size,fivsed_millis()-start);
        drive_alert(1); return;
    }
    if(rc!=0){
        protocol_send_result(rid,slot,"READ_ERROR","SPI transaction failed during firmware acquisition",size,fivsed_millis()-start);
        drive_alert(1); return;
    }
    char target_id[PROTO_TARGET_ID_MAX];
    slot_target_id(slot,info.jedec,target_id);
    handle_digest_result(rid,slot,target_id,target_id,digest,size,fivsed_millis()-start,info.jedec);
}

static void handle_stream_start(const protocol_frame_t *frame,const char *json){
    const uint8_t slot=json_slot_value(json,"\"slot\"",255u);
    uint32_t total=0u;
    char target_id[PROTO_TARGET_ID_MAX]={0};
    char physical_id[PHYSICAL_ID_MAX]={0};
    if(slot>=MAX_SLOTS || !json_u32_value(json,"\"total_bytes\"",&total) || total==0u || total>STREAM_MAX_BYTES || !json_string_value(json,"\"target_id\"",target_id,sizeof(target_id))){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"INVALID_STREAM_START\"}"); return;
    }
    (void)json_string_value(json,"\"physical_id\"",physical_id,sizeof(physical_id));
    if(!reference_storage_ok()){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"REFERENCE_STORAGE_INVALID\"}"); return;
    }
    const reference_slot_t *ref=reference_get(slot);
    if(ref && ref->used && strcmp(ref->target_id,target_id)!=0){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"TARGET_ID_MISMATCH\"}"); return;
    }

    memset(&g_stream,0,sizeof(g_stream));
    g_stream.active=1u;
    g_stream.request_id=frame->request_id;
    g_stream.slot=slot;
    g_stream.next_sequence=0u;
    g_stream.total_bytes=total;
    g_stream.start_ms=fivsed_millis();
    strncpy(g_stream.target_id,target_id,PROTO_TARGET_ID_MAX-1u);
    g_stream.target_id[PROTO_TARGET_ID_MAX-1u]='\0';
    strncpy(g_stream.physical_id,physical_id,PHYSICAL_ID_MAX-1u);
    g_stream.physical_id[PHYSICAL_ID_MAX-1u]='\0';
    sha256_init(&g_stream.sha);
    protocol_send_simple(MSG_STREAM_ACK,frame->request_id,frame->sequence,"{\"accepted\":true,\"stage\":\"STREAMING_TO_STM32\"}");
}

static void handle_stream_data(const protocol_frame_t *frame){
    if(!g_stream.active || frame->request_id!=g_stream.request_id || frame->sequence!=g_stream.next_sequence){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"STREAM_SEQUENCE_ERROR\"}"); return;
    }
    if(frame->length==0u || frame->length>PROTO_MAX_PAYLOAD || g_stream.processed_bytes+(uint32_t)frame->length>g_stream.total_bytes){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"STREAM_LENGTH_ERROR\"}"); return;
    }
    sha256_update(&g_stream.sha,frame->payload,frame->length);
    for(uint16_t i=0;i<frame->length;i++){
        if(frame->payload[i]!=0xFFu){g_stream.non_ff_seen=1u;break;}
    }
    g_stream.processed_bytes+=(uint32_t)frame->length;
    g_stream.next_sequence=(uint16_t)(g_stream.next_sequence+1u);
    char ack[160];
    const int n=snprintf(ack,sizeof(ack),"{\"bytes_processed\":%lu,\"total_bytes\":%lu}",(unsigned long)g_stream.processed_bytes,(unsigned long)g_stream.total_bytes);
    if(n>=0 && n<(int)sizeof(ack))protocol_send(MSG_STREAM_ACK,frame->request_id,frame->sequence,(const uint8_t*)ack,(uint16_t)n);
    if((g_stream.processed_bytes%(32u*1024u))==0u || g_stream.processed_bytes==g_stream.total_bytes){
        protocol_send_progress(frame->request_id,frame->sequence,"STM32_CALCULATING_SHA256",g_stream.processed_bytes,g_stream.total_bytes);
        protocol_tick();
    }
}

static void handle_stream_end(const protocol_frame_t *frame){
    if(!g_stream.active || frame->request_id!=g_stream.request_id || frame->sequence!=g_stream.next_sequence){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"STREAM_END_SEQUENCE_ERROR\"}"); return;
    }
    if(g_stream.processed_bytes!=g_stream.total_bytes || !g_stream.non_ff_seen){
        g_stream.active=0u;
        protocol_send_result(frame->request_id,g_stream.slot,"READ_ERROR",g_stream.processed_bytes!=g_stream.total_bytes?"Incomplete firmware stream":"Firmware image is all 0xFF; no readable firmware content was acquired",g_stream.processed_bytes,fivsed_millis()-g_stream.start_ms);
        drive_alert(1); return;
    }
    uint8_t digest[32];
    sha256_final(&g_stream.sha,digest);
    const uint8_t jedec[3]={0xEFu,0x40u,0x17u};
    const uint8_t slot=g_stream.slot;
    const uint32_t duration=fivsed_millis()-g_stream.start_ms;
    g_stream.active=0u;
    handle_digest_result(frame->request_id,slot,g_stream.target_id,g_stream.physical_id,digest,g_stream.total_bytes,duration,jedec);
}

int protocol_poll(protocol_frame_t *frame){
    uint8_t b;
    if(!fivsed_usb_read_byte(&b,1))return 0;
    if(b!=FIVSED_SYNC)return 0;
    if(!fivsed_usb_read_byte(&b,RX_BYTE_TIMEOUT_MS) || b!=FIVSED_VERSION)return 0;

    uint8_t head[11];
    for(uint8_t i=0u;i<11u;i++)if(!fivsed_usb_read_byte(&head[i],RX_BYTE_TIMEOUT_MS))return 0;
    frame->type=head[0]; frame->flags=head[1]; frame->reserved=head[2];
    frame->request_id=(uint32_t)head[3]|((uint32_t)head[4]<<8)|((uint32_t)head[5]<<16)|((uint32_t)head[6]<<24);
    frame->sequence=(uint16_t)head[7]|((uint16_t)head[8]<<8); frame->length=(uint16_t)head[9]|((uint16_t)head[10]<<8);
    if(frame->length>PROTO_MAX_PAYLOAD){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"PAYLOAD_TOO_LARGE\"}"); return 0;
    }
    for(uint16_t i=0u;i<frame->length;i++)if(!fivsed_usb_read_byte(&frame->payload[i],RX_BYTE_TIMEOUT_MS))return 0;
    uint8_t crc_b[2];
    if(!fivsed_usb_read_byte(&crc_b[0],RX_BYTE_TIMEOUT_MS)||!fivsed_usb_read_byte(&crc_b[1],RX_BYTE_TIMEOUT_MS))return 0;

    uint8_t crcbuf[12u+PROTO_MAX_PAYLOAD];
    crcbuf[0]=FIVSED_VERSION;
    memcpy(crcbuf+1,head,11);
    memcpy(crcbuf+12,frame->payload,frame->length);
    const uint16_t actual=crc16_ccitt(crcbuf,(uint32_t)12u+frame->length);
    const uint16_t expected=(uint16_t)crc_b[0]|((uint16_t)crc_b[1]<<8);
    if(actual!=expected){
        protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"CRC16_MISMATCH\"}"); return 0;
    }
    /* Any valid Pi frame proves the supervisor is alive. This also keeps the
       liveness lease fresh during a multi-minute 8 MiB firmware stream, when
       the Pi deliberately does not contend for the UART with a heartbeat. */
    g_pi_last_seen_ms=fivsed_millis();
    return 1;
}

void protocol_handle_frame(const protocol_frame_t *frame){
    char json[PROTO_MAX_PAYLOAD+1u];
    if(!frame || frame->length>=sizeof(json))return;
    memcpy(json,frame->payload,frame->length);json[frame->length]='\0';

    if(frame->type==MSG_HELLO_REQ){send_hello(frame->request_id);return;}
    if(frame->type==MSG_STATUS_REQ){send_status(frame->request_id);return;}
    if(frame->type==MSG_PI_HEARTBEAT){
        g_pi_last_seen_ms=fivsed_millis();
        char hb[240];
        const int n=snprintf(hb,sizeof(hb),"{\"pi_active\":true,\"stm32_active\":true,\"esp32_active\":%s,\"esp32_last_seen_ms\":%lu}",
            esp32_is_active()?"true":"false",(unsigned long)g_esp32_last_seen_ms);
        if(n>0 && n<(int)sizeof(hb))protocol_send(MSG_HEARTBEAT_RESP,frame->request_id,frame->sequence,(const uint8_t*)hb,(uint16_t)n);
        esp32_send_component_heartbeat();
        return;
    }
    if(frame->type==MSG_SELECT_SLOT){
        const uint8_t slot=(uint8_t)json_slot_value(json,"\"slot\"",0u);
        if(slot<MAX_SLOTS){
            provisioning_set_active_slot(slot);
            protocol_send_simple(MSG_ACK,frame->request_id,frame->sequence,"{\"ok\":true}");
        }else{
            protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"INVALID_TARGET_SLOT\"}");
        }
        return;
    }
    if(frame->type==MSG_SCAN_REQ){
        const uint8_t slot=(uint8_t)json_slot_value(json,"\"slot\"",255u);
        if(slot<MAX_SLOTS){
            provisioning_set_active_slot(slot);
            protocol_send_simple(MSG_ACK,frame->request_id,frame->sequence,"{\"accepted\":true}");
            handle_scan(frame->request_id,slot);
        }else{
            protocol_send_simple(MSG_NACK,frame->request_id,frame->sequence,"{\"error\":\"INVALID_TARGET_SLOT\"}");
        }
        return;
    }
    if(frame->type==MSG_STREAM_START){handle_stream_start(frame,json);return;}
    if(frame->type==MSG_STREAM_DATA){handle_stream_data(frame);return;}
    if(frame->type==MSG_STREAM_END){handle_stream_end(frame);return;}
}
