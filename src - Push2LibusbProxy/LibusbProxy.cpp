#include "LibusbProxy.h"
#include "Debug.h"
#include "FrameHandler.h"

#define PUSH2_TRANSFER_TIMEOUT 1000
#define PUSH2_BULK_EP_OUT 0x01

static int transferType = 0;

// ------------------------------------------------------------------------
// We'll store the handle to the original libusb-1.0.dll
// ------------------------------------------------------------------------
HMODULE g_hOriginalDll = NULL;
static libusb_callback_t g_original_callback = nullptr;
void* globalPush2Device = NULL;
void* globalPush2Handle = NULL;
bool newLiveFrame = false;

// ------------------------------------------------------------------------
// Static pointers to the real functions (from the original DLL)
// ------------------------------------------------------------------------
p_libusb_init                        real_libusb_init = NULL;
p_libusb_get_device_descriptor       real_libusb_get_device_descriptor = NULL;
p_libusb_get_device_list             real_libusb_get_device_list = NULL;
p_libusb_release_interface           real_libusb_release_interface = NULL;
p_libusb_exit                        real_libusb_exit = NULL;
p_libusb_bulk_transfer               real_libusb_bulk_transfer = NULL;
p_libusb_strerror                    real_libusb_strerror = NULL;
p_libusb_close                       real_libusb_close = NULL;
p_libusb_open                        real_libusb_open = NULL;
p_libusb_free_device_list            real_libusb_free_device_list = NULL;
p_libusb_claim_interface             real_libusb_claim_interface = NULL;
p_libusb_alloc_transfer              real_libusb_alloc_transfer = NULL;
p_libusb_free_transfer               real_libusb_free_transfer = NULL;
p_libusb_submit_transfer             real_libusb_submit_transfer = NULL;
p_libusb_cancel_transfer             real_libusb_cancel_transfer = NULL;
p_libusb_handle_events_timeout       real_libusb_handle_events_timeout = NULL;
p_libusb_set_option                  real_libusb_set_option = NULL;
p_libusb_error_name                  real_libusb_error_name = NULL;
p_libusb_hotplug_deregister_callback real_libusb_hotplug_deregister_callback = NULL;

bool loadOriginalLibusb()
{
    g_hOriginalDll = LoadLibraryA(ORIGINAL_LIBUSB_DLL);
    if (!g_hOriginalDll)
    {
        MessageBoxA(NULL, "Failed to load libusb-1.0.original.dll", "Proxy Error", MB_OK);
        DEBUG_LOG("PROXY_ERROR Failed to load '%s'", ORIGINAL_LIBUSB_DLL);
        return FALSE;
    }

    DEBUG_LOG("Loaded: '%s', now getting the entry points", ORIGINAL_LIBUSB_DLL);

    real_libusb_init = (p_libusb_init)GetProcAddress(g_hOriginalDll, "libusb_init");
    real_libusb_get_device_descriptor = (p_libusb_get_device_descriptor)GetProcAddress(g_hOriginalDll, "libusb_get_device_descriptor");
    real_libusb_get_device_list = (p_libusb_get_device_list)GetProcAddress(g_hOriginalDll, "libusb_get_device_list");
    real_libusb_release_interface = (p_libusb_release_interface)GetProcAddress(g_hOriginalDll, "libusb_release_interface");
    real_libusb_exit = (p_libusb_exit)GetProcAddress(g_hOriginalDll, "libusb_exit");
    real_libusb_bulk_transfer = (p_libusb_bulk_transfer)GetProcAddress(g_hOriginalDll, "libusb_bulk_transfer");
    real_libusb_strerror = (p_libusb_strerror)GetProcAddress(g_hOriginalDll, "libusb_strerror");
    real_libusb_close = (p_libusb_close)GetProcAddress(g_hOriginalDll, "libusb_close");
    real_libusb_open = (p_libusb_open)GetProcAddress(g_hOriginalDll, "libusb_open");
    real_libusb_free_device_list = (p_libusb_free_device_list)GetProcAddress(g_hOriginalDll, "libusb_free_device_list");
    real_libusb_claim_interface = (p_libusb_claim_interface)GetProcAddress(g_hOriginalDll, "libusb_claim_interface");
    real_libusb_alloc_transfer = (p_libusb_alloc_transfer)GetProcAddress(g_hOriginalDll, "libusb_alloc_transfer");
    real_libusb_free_transfer = (p_libusb_free_transfer)GetProcAddress(g_hOriginalDll, "libusb_free_transfer");
    real_libusb_submit_transfer = (p_libusb_submit_transfer)GetProcAddress(g_hOriginalDll, "libusb_submit_transfer");
    real_libusb_cancel_transfer = (p_libusb_cancel_transfer)GetProcAddress(g_hOriginalDll, "libusb_cancel_transfer");
    real_libusb_handle_events_timeout = (p_libusb_handle_events_timeout)GetProcAddress(g_hOriginalDll, "libusb_handle_events_timeout");
    real_libusb_set_option = (p_libusb_set_option)GetProcAddress(g_hOriginalDll, "libusb_set_option");
    real_libusb_error_name = (p_libusb_error_name)GetProcAddress(g_hOriginalDll, "libusb_error_name");
    real_libusb_hotplug_deregister_callback = (p_libusb_hotplug_deregister_callback)GetProcAddress(g_hOriginalDll, "libusb_hotplug_deregister_callback");

    return true;
}

bool deleteOriginalLibUsb()
{
    DEBUG_LOG("DllMain: Trying to release libusb-1.0.orig.dll");

    if (g_hOriginalDll)
    {
        DEBUG_LOG("Freeing '<original_dll process>'");
        FreeLibrary(g_hOriginalDll);
        g_hOriginalDll = NULL;
    }
    else
    {
        DEBUG_LOG("'<original_dll process>' is not assigned");
    }

    return true;
}

// ------------------------------------------------------------------------
// Proxy for libusb_init
// ------------------------------------------------------------------------
static void* globalCtx = nullptr;

extern "C" __declspec(dllexport)
int libusb_init(void* ctx)
{
    DEBUG_LOG("In libusb_init");

    int result = real_libusb_init(globalCtx);
    ctx = (void*)"Xanadu 2025";

    return 0;
}

extern "C" __declspec(dllexport)
int libusb_set_option(void* ctx, int option)
{
    DEBUG_LOG("In libusb_set_option");

    int result = real_libusb_set_option(ctx, option);
    return result;
}

// ------------------------------------------------------------------------
// Proxy for libusb_get_device_list
// ------------------------------------------------------------------------
extern "C" __declspec(dllexport)
long long libusb_get_device_list(void* ctx, void*** list)
{
    DEBUG_LOG("libusb_get_device_list %p text %s", ctx, ctx);

    if (!real_libusb_get_device_list)
    {
        DEBUG_LOG("RETURN -1 (missing real pointer)");
        return -1;
    }

    long long result = real_libusb_get_device_list(ctx, list);

    struct libusb_device** devices = (struct libusb_device**)(*list);
    struct libusb_device* push2_dev = NULL;

    for (int i = 0; i < result; i++)
    {
        struct libusb_device* dev = devices[i];
        struct libusb_device_descriptor desc;
        int ret = real_libusb_get_device_descriptor(dev, &desc);

        if (ret == 0)
        {
            if (desc.idVendor == 0x2982 && desc.idProduct == 0x1967)
            {
                DEBUG_LOG("Push2 device at %p:", dev);
                globalPush2Device = dev;
                push2_dev = dev;
                DEBUG_LOG("    Vendor ID: 0x%04x", desc.idVendor);
                DEBUG_LOG("    Product ID: 0x%04x", desc.idProduct);
                break;
            }
        }
        else
        {
            DEBUG_LOG("Failed to get descriptor for device %d at %p", i, dev);
        }
    }

    if (push2_dev)
    {
        struct libusb_device** new_list = (struct libusb_device**)malloc(2 * sizeof(struct libusb_device*));
        if (new_list)
        {
            new_list[0] = push2_dev;
            new_list[1] = NULL;
            *list = (void**)new_list;
        }
        result = 1;
    }
    else
    {
        struct libusb_device** new_list = (struct libusb_device**)malloc(sizeof(struct libusb_device*));
        if (new_list)
        {
            new_list[0] = NULL;
            *list = (void**)new_list;
        }
        result = 0;
    }

    return result;
}

extern "C" __declspec(dllexport)
void libusb_free_device_list(void** list, int unref_devices)
{
    DEBUG_LOG("In libusb_free_device_list");
    real_libusb_free_device_list(list, unref_devices);
}

// ------------------------------------------------------------------------
// Proxy for libusb_get_device_descriptor
// ------------------------------------------------------------------------
extern "C" __declspec(dllexport)
int libusb_get_device_descriptor(void* dev, void* desc)
{
    DEBUG_LOG("In libusb_get_device_descriptor");
    int result = real_libusb_get_device_descriptor(dev, desc);
    return result;
}

extern "C" __declspec(dllexport)
int libusb_open(void* dev, void** dev_handle)
{
    DEBUG_LOG("In libusb_open");

    int result = real_libusb_open(dev, dev_handle);

    if (result == 0 && dev_handle && *dev_handle)
    {
        globalPush2Handle = *dev_handle;
        DEBUG_LOG("libusb_open: cached globalPush2Handle=%p", globalPush2Handle);

        if (!EnsureNamedPipeServerStarted())
        {
            DEBUG_LOG("{LIBUSB} libusb_open: failed to start NamedPipeServer");
        }
    }

    return result;
}

extern "C" __declspec(dllexport)
void libusb_close(void* dev_handle)
{
    DEBUG_LOG("In libusb_close");

    if (globalPush2Handle == dev_handle)
    {
        DEBUG_LOG("libusb_close: cleared globalPush2Handle=%p", globalPush2Handle);
        globalPush2Handle = NULL;
    }

    real_libusb_close(dev_handle);
}

extern "C" __declspec(dllexport)
int libusb_claim_interface(struct libusb_device_handle* dev_handle, int interface_number)
{
    DEBUG_LOG("In libusb_claim_interface");
    int result = real_libusb_claim_interface(dev_handle, interface_number);
    return result;
}

extern "C" __declspec(dllexport)
int libusb_release_interface(void* dev_handle, int interface_number)
{
    DEBUG_LOG("libusb_release_interface");
    int result = real_libusb_release_interface(dev_handle, interface_number);
    return result;
}

extern "C" __declspec(dllexport)
void* libusb_alloc_transfer(int iso_packets)
{
    DEBUG_LOG("libusb_alloc_transfer");
    void* result = real_libusb_alloc_transfer(iso_packets);
    return result;
}

extern "C" __declspec(dllexport)
void libusb_free_transfer(void* transfer)
{
    DEBUG_LOG("libusb_free_transfer");
    real_libusb_free_transfer(transfer);
}

extern "C" __declspec(dllexport)
void libusb_exit(void* ctx)
{
    DEBUG_LOG("In libusb_exit");
    real_libusb_exit(ctx);
}

extern "C" __declspec(dllexport)
int libusb_bulk_transfer(
    void* dev_handle,
    unsigned char endpoint,
    unsigned char* data,
    int length,
    int* transferred,
    unsigned int timeout
)
{
    int result = real_libusb_bulk_transfer(dev_handle, endpoint, data, length, transferred, timeout);
    return result;
}

extern "C" __declspec(dllexport)
const char* libusb_strerror(int errcode)
{
    const char* result = real_libusb_strerror(errcode);

    if (result)
    {
        DEBUG_LOG("In libusb_strerror %d RETURN \"%s\"", errcode, result);
    }
    else
    {
        DEBUG_LOG("In libusb_strerror %d RETURN (null)", errcode);
    }

    return result;
}

extern "C"
void blend_frame(unsigned char* buffer, int source)
{
    const int width = 960;
    const int height = 160;
    const int lineTotalBytes = 2048;

    LARGE_INTEGER start, end, freq;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    RGB* liveData = livePixels->getData();
    RGB* maxData = maxPixels->getData();
    BlendPixel* blendData = blendPixels->getData();

    DEBUG_LOG("Blend: livePixels->data=%p, maxPixels->data=%p, blendPixels->data=%p, source %d", liveData, maxData, blendData, source);

    unsigned short* xorTable = new unsigned short[width];

    for (int x = 0; x < width; ++x)
    {
        xorTable[x] = (x & 1) ? 0xFFE7 : 0xF3E7;
    }

    for (int y = 0; y < height; y++)
    {
        unsigned char* rowPtr = buffer + y * lineTotalBytes;
        unsigned short* pixelRow = reinterpret_cast<unsigned short*>(rowPtr);
        int rowOffset = y * width;

        for (int x = 0; x < width; x++)
        {
            RGB live;

            if (source == 0)
            {
                unsigned short packedLive = pixelRow[x] ^ xorTable[x];

                live.r = static_cast<unsigned char>(((packedLive >> 0) & 0x1F) << 3);
                live.g = static_cast<unsigned char>(((packedLive >> 5) & 0x3F) << 2);
                live.b = static_cast<unsigned char>(((packedLive >> 11) & 0x1F) << 3);

                liveData[rowOffset + x] = live;
            }

            BlendPixel bp = blendData[rowOffset + x];

            if (bp.live == 200 && bp.max == 0)
            {
                unsigned short packedLive;

                if (source == 1)
                {
                    live = liveData[rowOffset + x];
                    packedLive = ((live.b >> 3) << 11) | ((live.g >> 2) << 5) | (live.r >> 3);
                    pixelRow[x] = packedLive ^ xorTable[x];
                }

                continue;
            }
            else if (bp.live == 0 && bp.max == 200)
            {
                RGB maxPix = maxData[rowOffset + x];
                unsigned short packedMax = ((maxPix.b >> 3) << 11) | ((maxPix.g >> 2) << 5) | (maxPix.r >> 3);
                pixelRow[x] = packedMax ^ xorTable[x];
                continue;
            }
            else
            {
                if (source == 1)
                {
                    live = liveData[rowOffset + x];
                }

                RGB maxPix = maxData[rowOffset + x];

                float liveFactor = bp.live / 200.0f;
                float maxFactor = bp.max / 200.0f;

                float rFloat = live.r * liveFactor + maxPix.r * maxFactor;
                float gFloat = live.g * liveFactor + maxPix.g * maxFactor;
                float bFloat = live.b * liveFactor + maxPix.b * maxFactor;

                unsigned int rVal = static_cast<unsigned int>(rFloat);
                unsigned int gVal = static_cast<unsigned int>(gFloat);
                unsigned int bVal = static_cast<unsigned int>(bFloat);

                if (rVal > 255) rVal = 255;
                if (gVal > 255) gVal = 255;
                if (bVal > 255) bVal = 255;

                unsigned char r = static_cast<unsigned char>(rVal);
                unsigned char g = static_cast<unsigned char>(gVal);
                unsigned char b = static_cast<unsigned char>(bVal);

                unsigned short packedBlended = ((b >> 3) << 11) | ((g >> 2) << 5) | (r >> 3);
                pixelRow[x] = packedBlended ^ xorTable[x];
            }
        }
    }
}

static void* transferFrame = nullptr;
static unsigned char* liveBuffer = nullptr;
static unsigned char headerTransfer[sizeof(libusb_transfer)];
static void* headerPtr = nullptr;

DWORD WINAPI FakeCallbackThread(LPVOID lpParam)
{
    Sleep(1);

    libusb_transfer* transfer = reinterpret_cast<libusb_transfer*>(lpParam);
    libusb_transfer* tr = (libusb_transfer*)transfer;

    if (transfer->callback)
    {
        transfer->callback(transfer);
    }

    return 0;
}

extern "C" __declspec(dllexport)
int libusb_submit_transfer(void* transfer)
{
    const int bodyFrameBytes = 327680;
    const int headerFrameBytes = 16;

    libusb_transfer* tr = reinterpret_cast<libusb_transfer*>(transfer);
    int result = 0;

    if (transferType == 0 && tr->length == headerFrameBytes)
    {
        DEBUG_LOG("\n>> libusb_submit_transfer LIVE HEADER");
        DEBUG_LOG("<< libusb_submit_transfer LIVE HEADER");
        MaybeFallbackToLiveOnLiveFrame();
        return result;
    }
    else if (transferType == 0 && tr->length == bodyFrameBytes)
    {
        DEBUG_LOG("\n>> libusb_submit_transfer LIVE BODY");

        tr->actual_length = tr->length;

        if (!EnsureNamedPipeServerStarted())
        {
            DEBUG_LOG("{LIBUSB} LIVE BODY: failed to ensure NamedPipeServer started");
        }

        CacheLastLiveFrame(tr->buffer, tr->length);
        EnsureFadeTimerStarted();

        blend_frame(tr->buffer, 0);
        globalPush2Handle = tr->dev_handle;
        newLiveFrame = true;
        display_frame(tr->buffer);

        HANDLE hThread = CreateThread(
            NULL,
            0,
            FakeCallbackThread,
            transfer,
            0,
            NULL
        );

        if (hThread != NULL)
        {
            CloseHandle(hThread);
        }

        DEBUG_LOG("<< libusb_submit_transfer LIVE BODY");
        return 0;
    }

    return result;
}

extern "C" __declspec(dllexport)
int libusb_cancel_transfer(void* transfer)
{
    int result = real_libusb_cancel_transfer(transfer);
    return result;
}

extern "C" __declspec(dllexport)
int libusb_handle_events_timeout(void* ctx, void* tv)
{
    int result = -1;

    __try
    {
        result = real_libusb_handle_events_timeout(globalCtx, tv);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        DWORD code = GetExceptionCode();
        DEBUG_LOG("Exception thrown in libusb_handle_events_timeout, code = 0x%08X", code);
        return -1;
    }

    return 0;
}

extern "C" __declspec(dllexport)
const char* libusb_error_name(int errcode)
{
    const char* result = real_libusb_error_name(errcode);
    DEBUG_LOG("Error with errcode %d = '%s'", errcode, result ? result : "NULL");
    return result;
}

extern "C" __declspec(dllexport)
int libusb_hotplug_deregister_callback(void* ctx, void* callback_handle)
{
    int result = real_libusb_hotplug_deregister_callback(ctx, callback_handle);
    return result;
}

extern "C" __declspec(dllexport)
int libusb_hotplug_register_callback(
    void* ctx,
    int events,
    int flags,
    int vendor_id,
    int product_id,
    int dev_class,
    void* callback,
    void* user_data,
    void** callback_handle
)
{
    return -5;
}