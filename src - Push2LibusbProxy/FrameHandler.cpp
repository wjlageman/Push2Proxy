#include "FrameHandler.h"
#include "LibusbProxy.h"
#include "NamedPipeServer.h"
#include "Debug.h"
#include <exception>
#include <atomic>
#include <vector>
#include <cstring>

CRITICAL_SECTION g_displayLock;

Push2Matrix<RGB>* livePixels = nullptr;
Push2Matrix<RGB>* maxPixels = nullptr;
Push2Matrix<BlendPixel>* blendPixels = nullptr;

static std::atomic<ULONGLONG> g_keepalive_deadline_ms{ ~0ULL };

static const int kFullFrameBytes = 327680;

void initFrameHandler()
{
    InitializeCriticalSection(&g_displayLock);

    DEBUG_LOG("initFrameHandler");
    livePixels = new Push2Matrix<RGB>();
    maxPixels = new Push2Matrix<RGB>();
    blendPixels = new Push2Matrix<BlendPixel>();

    RGB black = { 0, 0, 0 };
    livePixels->fill(black);
    maxPixels->fill(black);

    BlendPixel runtimeBlend = { 200, 0 };
    blendPixels->fill(runtimeBlend);

    g_keepalive_deadline_ms.store(~0ULL, std::memory_order_relaxed);
}

void TouchMaxKeepalive(DWORD extend_ms)
{
    g_keepalive_deadline_ms.store(GetTickCount64() + extend_ms, std::memory_order_relaxed);
}

void MaybeFallbackToLiveOnLiveFrame()
{
    // In this version not active
    return;

    const ULONGLONG now = GetTickCount64();
    const ULONGLONG deadline = g_keepalive_deadline_ms.load(std::memory_order_relaxed);

    if (now > deadline)
    {
        DEBUG_LOG("Deadline to kick out Max reached: Stop blending frames, Live frames only from here");

        EnterCriticalSection(&g_displayLock);

        RGB black = { 0, 0, 0 };
        maxPixels->fill(black);

        BlendPixel defaultBlend = { 200, 0 };
        blendPixels->fill(defaultBlend);

        LeaveCriticalSection(&g_displayLock);

        g_keepalive_deadline_ms.store(~0ULL, std::memory_order_relaxed);
    }
}

extern "C" __declspec(dllexport)
int process_frame_max()
{
    DEBUG_LOG("In process_frame_max");

    unsigned char buffer[kFullFrameBytes];
    blend_frame(buffer, 1);
    return display_frame(buffer);
}

extern "C" __declspec(dllexport)
int display_frame(unsigned char* buffer)
{
    DEBUG_LOG("In send display_frame");

    const int headerSize = 16;
    const int fullFrameBytes = kFullFrameBytes;

    int actual_length = 0;
    int result = 0;

    unsigned char PUSH2_DISPLAY_FRAME_HEADER[headerSize] =
    {
        0xFF, 0xCC, 0xAA, 0x88,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00
    };

    if (!TryEnterCriticalSection(&g_displayLock))
    {
        DEBUG_LOG("display_frame: Overlapping call rejected");
        return -1;
    }

    DEBUG_LOG("Bulk_transfer 1 sending header %d", headerSize);

    result = real_libusb_bulk_transfer(
        globalPush2Handle,
        PUSH2_BULK_EP_OUT,
        PUSH2_DISPLAY_FRAME_HEADER,
        headerSize,
        &actual_length,
        PUSH2_TRANSFER_TIMEOUT
    );

    if (result == 0)
    {
        DEBUG_LOG("Bulk_transfer 2 sending body %d", fullFrameBytes);

        result = real_libusb_bulk_transfer(
            globalPush2Handle,
            PUSH2_BULK_EP_OUT,
            buffer,
            fullFrameBytes,
            &actual_length,
            PUSH2_TRANSFER_TIMEOUT
        );
    }

    LeaveCriticalSection(&g_displayLock);
    return result;
}