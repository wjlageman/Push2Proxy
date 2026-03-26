#pragma once

#include <windows.h>

void takeover_init();
void takeover_free();

void takeover_send_bang();
void takeover_send_reactivate_bang();

void takeover_start_listener();
void takeover_stop_listener();

bool takeover_is_taken_over();

void takeover_lock_pipe();
void takeover_unlock_pipe();