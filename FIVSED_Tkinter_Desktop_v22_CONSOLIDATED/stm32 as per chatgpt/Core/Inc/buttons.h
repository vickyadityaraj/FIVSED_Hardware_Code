#ifndef FIVSED_BUTTONS_H
#define FIVSED_BUTTONS_H
#include <stdint.h>

enum { BTN_NONE = -1, BTN_REGISTER = 0, BTN_REFERENCE_UPDATE = 1, BTN_REVOKE = 2, BTN_RESTORE = 3 };

void buttons_init(void);
int buttons_poll(void);
void button_apply_local_action(int button);
void provisioning_set_active_slot(uint8_t slot);
int provisioning_register_armed(void);
int provisioning_reference_update_armed(void);
void provisioning_clear_register(void);
void provisioning_clear_reference_update(void);

#endif
