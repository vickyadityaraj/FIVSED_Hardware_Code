#include "sha256_engine.h"
#include <string.h>

#define ROTR(x,n) (((x) >> (n)) | ((x) << (32u-(n))))
#define CH(x,y,z) (((x)&(y)) ^ (~(x)&(z)))
#define MAJ(x,y,z) (((x)&(y)) ^ ((x)&(z)) ^ ((y)&(z)))
#define BSIG0(x) (ROTR((x),2)^ROTR((x),13)^ROTR((x),22))
#define BSIG1(x) (ROTR((x),6)^ROTR((x),11)^ROTR((x),25))
#define SSIG0(x) (ROTR((x),7)^ROTR((x),18)^((x)>>3))
#define SSIG1(x) (ROTR((x),17)^ROTR((x),19)^((x)>>10))

static const uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

static uint32_t load_be32(const uint8_t *p) { return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3]; }
static void store_be32(uint8_t *p, uint32_t v) { p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v; }

static void transform(sha256_ctx_t *ctx, const uint8_t data[64]) {
    uint32_t w[64];
    for (uint32_t i=0;i<16;i++) w[i]=load_be32(data+i*4);
    for (uint32_t i=16;i<64;i++) w[i]=SSIG1(w[i-2])+w[i-7]+SSIG0(w[i-15])+w[i-16];
    uint32_t a=ctx->state[0],b=ctx->state[1],c=ctx->state[2],d=ctx->state[3];
    uint32_t e=ctx->state[4],f=ctx->state[5],g=ctx->state[6],h=ctx->state[7];
    for (uint32_t i=0;i<64;i++) {
        uint32_t t1=h+BSIG1(e)+CH(e,f,g)+K[i]+w[i];
        uint32_t t2=BSIG0(a)+MAJ(a,b,c);
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    ctx->state[0]+=a;ctx->state[1]+=b;ctx->state[2]+=c;ctx->state[3]+=d;
    ctx->state[4]+=e;ctx->state[5]+=f;ctx->state[6]+=g;ctx->state[7]+=h;
}

void sha256_init(sha256_ctx_t *ctx) {
    static const uint32_t iv[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    memcpy(ctx->state,iv,sizeof(iv)); ctx->total_len=0; ctx->buffer_len=0;
}

void sha256_update(sha256_ctx_t *ctx, const uint8_t *data, uint32_t len) {
    ctx->total_len += len;
    while (len) {
        uint32_t take = 64u - ctx->buffer_len;
        if (take > len) take=len;
        memcpy(ctx->buffer+ctx->buffer_len,data,take);
        ctx->buffer_len += take; data += take; len -= take;
        if (ctx->buffer_len == 64u) { transform(ctx,ctx->buffer); ctx->buffer_len=0; }
    }
}

void sha256_final(sha256_ctx_t *ctx, uint8_t out[32]) {
    uint64_t bit_len = ctx->total_len * 8ULL;
    uint8_t pad[128] = {0x80};
    uint32_t pad_len = (ctx->buffer_len < 56u) ? (56u-ctx->buffer_len) : (120u-ctx->buffer_len);
    sha256_update(ctx,pad,pad_len);
    uint8_t lenbuf[8];
    for (int i=0;i<8;i++) lenbuf[7-i]=(uint8_t)(bit_len>>(i*8));
    sha256_update(ctx,lenbuf,8);
    for (int i=0;i<8;i++) store_be32(out+i*4,ctx->state[i]);
}

void sha256_hmac(const uint8_t *key, uint32_t key_len, const uint8_t *msg, uint32_t msg_len, uint8_t out[32]) {
    uint8_t k0[64]={0};
    if (key_len > 64u) { sha256_ctx_t kc; sha256_init(&kc); sha256_update(&kc,key,key_len); sha256_final(&kc,k0); key_len=32; }
    else memcpy(k0,key,key_len);
    uint8_t ipad[64],opad[64];
    for (int i=0;i<64;i++) { ipad[i]=(uint8_t)(k0[i]^0x36u); opad[i]=(uint8_t)(k0[i]^0x5cu); }
    sha256_ctx_t inner; uint8_t inner_hash[32];
    sha256_init(&inner); sha256_update(&inner,ipad,64); sha256_update(&inner,msg,msg_len); sha256_final(&inner,inner_hash);
    sha256_ctx_t outer; sha256_init(&outer); sha256_update(&outer,opad,64); sha256_update(&outer,inner_hash,32); sha256_final(&outer,out);
}

