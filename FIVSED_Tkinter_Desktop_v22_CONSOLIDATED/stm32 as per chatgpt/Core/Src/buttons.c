#include "buttons.h"
#include "main.h"
#include "platform.h"
#include "reference_store.h"
#include "stm32f411_min.h"

#define HOLD_CONFIRM_MS 1500u
#define DEBOUNCE_MS 30u

static uint32_t down_at[4];
static uint8_t stable[4];
static uint8_t active_slot;
static volatile uint8_t register_armed;
static volatile uint8_t reference_update_armed;

static uint8_t pressed(int b){
    if(b==BTN_REGISTER)return (GPIO_IDR(GPIOA)&(1UL<<0))==0;
    if(b==BTN_REFERENCE_UPDATE)return (GPIO_IDR(GPIOB)&(1UL<<4))==0;
    if(b==BTN_REVOKE)return (GPIO_IDR(GPIOB)&(1UL<<5))==0;
    return (GPIO_IDR(GPIOA)&(1UL<<1))==0;
}

void buttons_init(void){ for(int i=0;i<4;i++){down_at[i]=0;stable[i]=0;} active_slot=0; register_armed=0; reference_update_armed=0; }
void provisioning_set_active_slot(uint8_t slot){ if(slot<MAX_SLOTS)active_slot=slot; }
int provisioning_register_armed(void){return register_armed!=0;}
int provisioning_reference_update_armed(void){return reference_update_armed!=0;}
void provisioning_clear_register(void){register_armed=0;}
void provisioning_clear_reference_update(void){reference_update_armed=0;}

int buttons_poll(void){
    uint32_t now=fivsed_millis();
    for(int b=0;b<4;b++){
        uint8_t raw=pressed(b);
        if(raw){
            if(down_at[b]==0)down_at[b]=now;
            if(!stable[b] && (now-down_at[b])>=DEBOUNCE_MS)stable[b]=1;
        }else{
            if(stable[b]){
                uint32_t held=now-down_at[b];
                down_at[b]=0;stable[b]=0;
                if((b==BTN_REGISTER || b==BTN_REFERENCE_UPDATE) && held<HOLD_CONFIRM_MS)continue;
                return b;
            }
            down_at[b]=0;
        }
    }
    return BTN_NONE;
}

/* Called after buttons_poll returns a button id. Security-changing operations are
   local physical actions only; no UART/web command can trigger these flags. */
void button_apply_local_action(int button){
    if(button==BTN_REGISTER){ if(!reference_is_valid(active_slot))register_armed=1; }
    else if(button==BTN_REFERENCE_UPDATE){ if(reference_is_valid(active_slot))reference_update_armed=1; }
    else if(button==BTN_REVOKE){ (void)reference_revoke(active_slot); }
    else if(button==BTN_RESTORE){ (void)reference_restore(active_slot); }
}
