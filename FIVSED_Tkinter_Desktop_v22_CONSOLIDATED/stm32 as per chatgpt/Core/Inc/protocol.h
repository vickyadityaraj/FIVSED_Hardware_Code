#ifndef FIVSED_PROTOCOL_H
#define FIVSED_PROTOCOL_H
#include <stdint.h>

#define FIVSED_SYNC 0xF5u
#define FIVSED_VERSION 1u
#define PROTO_MAX_PAYLOAD 1024u
#define PROTO_TARGET_ID_MAX 32u

enum {
    MSG_HELLO_REQ = 0x01,
    MSG_HELLO_RESP = 0x81,
    MSG_STATUS_REQ = 0x02,
    MSG_STATUS_RESP = 0x82,
    MSG_SELECT_SLOT = 0x03,
    MSG_SCAN_REQ = 0x04,
    MSG_PI_HEARTBEAT = 0x05,
    MSG_STREAM_START = 0x10,
    MSG_STREAM_DATA = 0x11,
    MSG_STREAM_END = 0x12,
    MSG_STREAM_ACK = 0x13,
    MSG_ACK = 0x06,
    MSG_NACK = 0x07,
    MSG_HEARTBEAT_RESP = 0x83,
    MSG_SCAN_PROGRESS = 0x85,
    MSG_SCAN_RESULT = 0x86,
    MSG_EVENT = 0x90,
    MSG_COMPONENT_HEARTBEAT = 0x91,
    MSG_ERROR = 0xE0
};

typedef struct {
    uint8_t type;
    uint8_t flags;
    uint8_t reserved;
    uint32_t request_id;
    uint16_t sequence;
    uint16_t length;
    uint8_t payload[PROTO_MAX_PAYLOAD];
} protocol_frame_t;

void protocol_init(void);
int protocol_poll(protocol_frame_t *frame);
void protocol_send(uint8_t type, uint32_t request_id, uint16_t sequence, const uint8_t *payload, uint16_t len);
void protocol_handle_frame(const protocol_frame_t *frame);
void protocol_send_result(uint32_t request_id, uint8_t slot, const char *result, const char *reason,
                          uint32_t firmware_size, uint32_t duration_ms);
void protocol_send_progress(uint32_t request_id, uint16_t sequence, const char *stage, uint32_t done, uint32_t total);
void protocol_tick(void);

#endif
