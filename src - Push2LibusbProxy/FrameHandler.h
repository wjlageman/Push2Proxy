#pragma once

#include <windows.h>

#include "PipeMessageStructures.h"
#include "Push2Matrix.h"
#include "RGB.h"
#include "BlendPixel.h"

#define PUSH2_BULK_EP_OUT 0x01
#define PUSH2_TRANSFER_TIMEOUT 1000
#define KEEP_MAX_ALIVE_TIMEOUT 2000

extern CRITICAL_SECTION g_displayLock;

extern "C" __declspec(dllexport) int display_frame(unsigned char* buffer);
extern DWORD WINAPI NamedPipeServerThread(LPVOID lpParam);
extern "C" void blend_frame(unsigned char* buffer, int source);

#define LIVE_SIZE   (LIVE_WIDTH * LIVE_HEIGHT * sizeof(RGB))
#define MAX_SIZE    LIVE_SIZE
#define BLEND_SIZE  (LIVE_WIDTH * LIVE_HEIGHT * sizeof(BlendPixel))
#define TOTAL_SIZE  (LIVE_SIZE + MAX_SIZE + BLEND_SIZE)

extern Push2Matrix<RGB>* livePixels;
extern Push2Matrix<RGB>* maxPixels;
extern Push2Matrix<BlendPixel>* blendPixels;

extern void* globalPush2Handle;

extern void initFrameHandler();

extern void TouchMaxKeepalive(DWORD extend_ms);
extern void MaybeFallbackToLiveOnLiveFrame();
extern "C" __declspec(dllexport) int process_frame_max();