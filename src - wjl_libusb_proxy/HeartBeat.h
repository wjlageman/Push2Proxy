#pragma once
//#include <windows.h>
#include "NamedPipeClient.h"
#include "PipeMessagesStructures.h"

extern bool startHeartbeat(NamedPipeClient* client, DWORD interval_ms);  // bv 500 ms
extern void stopHeartbeat();
