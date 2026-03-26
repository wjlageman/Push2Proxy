#include "SplashScreen.h"

#include "FrameHandler.h"
#include "Debug.h"
#include "WicPngLoader.h"
#include "resource.h"

#include <atomic>
#include <vector>
#include <cstring>

static Push2Matrix<BlendPixel>* g_startupBlendPixels = nullptr;

struct SplashStep
{
    DWORD duration_ms;
    unsigned char splash_in;
    unsigned char splash_out;
    unsigned char live_in;
    unsigned char live_out;
};

static const DWORD kSplashStartDelayMs = 0;

static const SplashStep kSplashSteps[] =
{
    {  900,      0,   200,   0,   0   },
    {  500,    200,   200,   0,   0   },
    {  700,    200,   200,   0, 200   },
    {  500,    200,     0, 200, 200   },
    {    0,      0,     0,   0,   0   }
};

static const DWORD kSplashTimerIntervalMs = 50;
static const int kFullFrameBytes = 327680;

static std::vector<unsigned char> g_last_live_frame;
static bool g_has_last_live_frame = false;

static std::vector<unsigned char> g_splash_base_live;

static HANDLE g_fade_timer_queue = NULL;
static HANDLE g_fade_timer = NULL;

struct StartupFadeState
{
    bool active;
    bool timer_started;
    ULONGLONG visible_start_ms;
    int step_index;
    ULONGLONG step_start_ms;
};

static StartupFadeState g_startup_fade = { false, false, 0, 0, 0 };

void EnsureFadeTimerStarted();
static void StopFadeTimer();
static void CaptureSplashBaseline();
static unsigned char LerpU8_0_200(unsigned char a, unsigned char b, float t);
static void FillBlackLiveFrame(unsigned char* buffer);
static void FillBlackMaxPixels();
static bool CopyLastLiveFrame(unsigned char* out, int length);
static bool ApplyCurrentStepAtTime(ULONGLONG now_ms, unsigned char* out_live_min_for_emit);
static void EmitFadeFrame();
static bool ApplySplashRgbaToMatrices(const RgbaImage& img);
static bool PrepareStartupSplash();

void StartSplashScreen()
{
    StopFadeTimer();

    g_startup_fade.active = false;
    g_startup_fade.timer_started = false;
    g_startup_fade.visible_start_ms = 0;
    g_startup_fade.step_index = 0;
    g_startup_fade.step_start_ms = 0;

    g_splash_base_live.clear();

    if (g_startupBlendPixels)
    {
        delete g_startupBlendPixels;
        g_startupBlendPixels = nullptr;
    }

    if (!PrepareStartupSplash())
    {
        DEBUG_LOG("SplashScreen: preparation failed, continuing without splash");
        return;
    }

    g_startup_fade.active = true;
    g_startup_fade.timer_started = false;
    g_startup_fade.visible_start_ms = 0;
    g_startup_fade.step_index = 0;
    g_startup_fade.step_start_ms = 0;

    g_splash_base_live.clear();

    DEBUG_LOG("SPLASH_SEQ: armed (delay=%u interval=%u)", kSplashStartDelayMs, kSplashTimerIntervalMs);

    // Do not start the timer here.
    // DllMain calls StartSplashScreen(), and creating timer infrastructure there is risky.
    // The timer is started later by normal runtime activity via EnsureFadeTimerStarted().
}

void CacheLastLiveFrame(const unsigned char* buffer, int length)
{
    if (!buffer || length != kFullFrameBytes)
    {
        return;
    }

    EnterCriticalSection(&g_displayLock);

    if (g_last_live_frame.size() != static_cast<size_t>(kFullFrameBytes))
    {
        g_last_live_frame.assign(static_cast<size_t>(kFullFrameBytes), 0);
    }

    memcpy(g_last_live_frame.data(), buffer, static_cast<size_t>(kFullFrameBytes));
    g_has_last_live_frame = true;

    LeaveCriticalSection(&g_displayLock);

    EnsureFadeTimerStarted();
}

static bool CopyLastLiveFrame(unsigned char* out, int length)
{
    if (!out || length != kFullFrameBytes)
    {
        return false;
    }

    bool ok = false;

    EnterCriticalSection(&g_displayLock);

    if (g_has_last_live_frame && g_last_live_frame.size() == static_cast<size_t>(kFullFrameBytes))
    {
        memcpy(out, g_last_live_frame.data(), static_cast<size_t>(kFullFrameBytes));
        ok = true;
    }

    LeaveCriticalSection(&g_displayLock);

    return ok;
}

static void CaptureSplashBaseline()
{
    if (!g_startupBlendPixels)
    {
        return;
    }

    const int width = g_startupBlendPixels->getWidth();
    const int height = g_startupBlendPixels->getHeight();
    const size_t count = static_cast<size_t>(width) * static_cast<size_t>(height);

    g_splash_base_live.assign(count, 200);

    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
        {
            const size_t i = static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x);
            g_splash_base_live[i] = g_startupBlendPixels->at(x, y).live;
        }
    }
}

static unsigned char LerpU8_0_200(unsigned char a, unsigned char b, float t)
{
    const float af = static_cast<float>(a);
    const float bf = static_cast<float>(b);

    float v = af + (bf - af) * t;
    if (v < 0.0f) v = 0.0f;
    if (v > 200.0f) v = 200.0f;

    return static_cast<unsigned char>(v + 0.5f);
}

static void FillBlackLiveFrame(unsigned char* buffer)
{
    if (!buffer)
    {
        return;
    }

    static unsigned short s_xor_table[960];
    static bool s_xor_table_init = false;

    if (!s_xor_table_init)
    {
        for (int x = 0; x < 960; ++x)
        {
            s_xor_table[x] = (x & 1) ? 0xFFE7 : 0xF3E7;
        }
        s_xor_table_init = true;
    }

    const int width = 960;
    const int height = 160;
    const int lineTotalBytes = 2048;

    memset(buffer, 0, static_cast<size_t>(kFullFrameBytes));

    for (int y = 0; y < height; ++y)
    {
        unsigned char* rowPtr = buffer + y * lineTotalBytes;
        unsigned short* pixelRow = reinterpret_cast<unsigned short*>(rowPtr);

        for (int x = 0; x < width; ++x)
        {
            pixelRow[x] = s_xor_table[x];
        }
    }
}

static void FillBlackMaxPixels()
{
    if (!maxPixels)
    {
        return;
    }

    const int width = maxPixels->getWidth();
    const int height = maxPixels->getHeight();

    RGB black = { 0, 0, 0 };

    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
        {
            maxPixels->at(x, y) = black;
        }
    }
}

static bool ApplyCurrentStepAtTime(ULONGLONG now_ms, unsigned char* out_live_min_for_emit)
{
    if (!g_startupBlendPixels || !blendPixels || !out_live_min_for_emit)
    {
        return false;
    }

    if (g_startup_fade.visible_start_ms == 0)
    {
        if (!globalPush2Handle)
        {
            return false;
        }

        g_startup_fade.visible_start_ms = now_ms;
        g_startup_fade.step_index = 0;
        g_startup_fade.step_start_ms = now_ms + static_cast<ULONGLONG>(kSplashStartDelayMs);

        CaptureSplashBaseline();

        DEBUG_LOG("SPLASH_SEQ: visible start now=%llu delay=%u", now_ms, kSplashStartDelayMs);
    }

    if (now_ms < g_startup_fade.step_start_ms)
    {
        return false;
    }

    while (true)
    {
        const SplashStep& step = kSplashSteps[g_startup_fade.step_index];

        if (step.duration_ms == 0)
        {
            *out_live_min_for_emit = 200;

            if (blendPixels)
            {
                BlendPixel liveOnly = { 200, 0 };
                blendPixels->fill(liveOnly);
            }

            FillBlackMaxPixels();

            if (g_startupBlendPixels)
            {
                delete g_startupBlendPixels;
                g_startupBlendPixels = nullptr;
            }

            g_splash_base_live.clear();
            g_last_live_frame.clear();
            g_has_last_live_frame = false;

            g_startup_fade.active = false;
            DEBUG_LOG("SPLASH_SEQ: completed");

            StopFadeTimer();
            return false;
        }

        const ULONGLONG elapsed = now_ms - g_startup_fade.step_start_ms;
        if (elapsed < static_cast<ULONGLONG>(step.duration_ms))
        {
            break;
        }

        g_startup_fade.step_start_ms += static_cast<ULONGLONG>(step.duration_ms);
        g_startup_fade.step_index += 1;
    }

    const SplashStep& step = kSplashSteps[g_startup_fade.step_index];

    const ULONGLONG elapsed = now_ms - g_startup_fade.step_start_ms;
    const float t = (step.duration_ms > 0) ? (static_cast<float>(elapsed) / static_cast<float>(step.duration_ms)) : 1.0f;
    const float p = (t < 0.0f) ? 0.0f : ((t > 1.0f) ? 1.0f : t);

    const unsigned char splash = LerpU8_0_200(step.splash_in, step.splash_out, p);
    const unsigned char live_factor = LerpU8_0_200(step.live_in, step.live_out, p);

    *out_live_min_for_emit = live_factor;

    const int width = g_startupBlendPixels->getWidth();
    const int height = g_startupBlendPixels->getHeight();
    const size_t count = static_cast<size_t>(width) * static_cast<size_t>(height);

    if (g_splash_base_live.size() != count)
    {
        CaptureSplashBaseline();
        if (g_splash_base_live.size() != count)
        {
            return false;
        }
    }

    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
        {
            const size_t i = static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x);

            const unsigned int base_live = static_cast<unsigned int>(g_splash_base_live[i]);
            const unsigned int base_max = 200u - base_live;

            const unsigned int max_w = (base_max * static_cast<unsigned int>(splash) + 100u) / 200u;
            const unsigned int live_w = (base_live * static_cast<unsigned int>(live_factor) + 100u) / 200u;

            BlendPixel bp;
            bp.live = static_cast<unsigned char>(live_w);
            bp.max = static_cast<unsigned char>(max_w);

            blendPixels->at(x, y) = bp;
        }
    }

    return true;
}

static void EmitFadeFrame()
{
    if (!globalPush2Handle)
    {
        return;
    }

    unsigned char buffer[kFullFrameBytes];

    if (!CopyLastLiveFrame(buffer, kFullFrameBytes))
    {
        FillBlackLiveFrame(buffer);
    }

    blend_frame(buffer, 0);
    display_frame(buffer);
}

static VOID CALLBACK FadeTimerProc(PVOID lpParameter, BOOLEAN timerOrWaitFired)
{
    (void)lpParameter;
    (void)timerOrWaitFired;

    static ULONGLONG s_last_tick_ms = 0;
    const ULONGLONG now0 = GetTickCount64();
    const ULONGLONG dt = (s_last_tick_ms == 0) ? 0 : (now0 - s_last_tick_ms);
    s_last_tick_ms = now0;

    DEBUG_LOG("SPLASH_SEQ: tick now=%llu dt=%llu active=%d has_live=%d has_handle=%d step=%d",
        now0,
        dt,
        g_startup_fade.active ? 1 : 0,
        g_has_last_live_frame ? 1 : 0,
        globalPush2Handle ? 1 : 0,
        g_startup_fade.step_index);

    if (!g_startup_fade.active)
    {
        return;
    }

    unsigned char live_factor_for_emit = 200;

    EnterCriticalSection(&g_displayLock);
    const bool ok = ApplyCurrentStepAtTime(now0, &live_factor_for_emit);
    LeaveCriticalSection(&g_displayLock);

    if (ok)
    {
        EmitFadeFrame();
    }
}

void EnsureFadeTimerStarted()
{
    if (!g_startup_fade.active)
    {
        return;
    }

    if (g_startup_fade.timer_started)
    {
        return;
    }

    if (!g_fade_timer_queue)
    {
        g_fade_timer_queue = CreateTimerQueue();
        if (!g_fade_timer_queue)
        {
            DEBUG_LOG("SPLASH_SEQ: CreateTimerQueue failed");
            return;
        }
    }

    if (!g_fade_timer)
    {
        if (!CreateTimerQueueTimer(
            &g_fade_timer,
            g_fade_timer_queue,
            FadeTimerProc,
            NULL,
            0,
            kSplashTimerIntervalMs,
            WT_EXECUTEDEFAULT))
        {
            DEBUG_LOG("SPLASH_SEQ: CreateTimerQueueTimer failed");
            g_fade_timer = NULL;
            return;
        }
    }

    g_startup_fade.timer_started = true;
    DEBUG_LOG("SPLASH_SEQ: timer started interval=%u", kSplashTimerIntervalMs);
}

static void StopFadeTimer()
{
    if (g_fade_timer)
    {
        DeleteTimerQueueTimer(g_fade_timer_queue, g_fade_timer, NULL);
        g_fade_timer = NULL;
    }

    if (g_fade_timer_queue)
    {
        DeleteTimerQueueEx(g_fade_timer_queue, NULL);
        g_fade_timer_queue = NULL;
    }

    g_startup_fade.timer_started = false;
}

static bool ApplySplashRgbaToMatrices(const RgbaImage& img)
{
    if (!maxPixels)
    {
        DEBUG_LOG("SplashScreen: maxPixels is null during splash init");
        return false;
    }

    if (!g_startupBlendPixels)
    {
        g_startupBlendPixels = new Push2Matrix<BlendPixel>();
    }

    const int dst_w = maxPixels->getWidth();
    const int dst_h = maxPixels->getHeight();

    if (img.width != dst_w || img.height != dst_h)
    {
        DEBUG_LOG("SplashScreen: splash PNG size mismatch: got %dx%d, expected %dx%d", img.width, img.height, dst_w, dst_h);
        return false;
    }

    if (img.rgba.size() != static_cast<size_t>(img.width) * static_cast<size_t>(img.height) * 4)
    {
        DEBUG_LOG("SplashScreen: splash PNG buffer size mismatch");
        return false;
    }

    for (int y = 0; y < dst_h; y++)
    {
        for (int x = 0; x < dst_w; x++)
        {
            const size_t idx = (static_cast<size_t>(y) * static_cast<size_t>(dst_w) + static_cast<size_t>(x)) * 4;
            const unsigned char r = img.rgba[idx + 0];
            const unsigned char g = img.rgba[idx + 1];
            const unsigned char b = img.rgba[idx + 2];
            const unsigned char a = img.rgba[idx + 3];

            RGB rgb = { r, g, b };
            maxPixels->at(x, y) = rgb;

            const unsigned char max_weight = static_cast<unsigned char>((static_cast<unsigned int>(a) * 200u) / 255u);
            const unsigned char live_weight = static_cast<unsigned char>(200u - max_weight);

            BlendPixel bp = { live_weight, max_weight };
            g_startupBlendPixels->at(x, y) = bp;
        }
    }

    return true;
}

static bool PrepareStartupSplash()
{
    HMODULE hm = NULL;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&PrepareStartupSplash),
        &hm
    );

    if (!hm)
    {
        DEBUG_LOG("SplashScreen: GetModuleHandleExW failed for splash resource lookup");
        return false;
    }

    if (g_startupBlendPixels)
    {
        delete g_startupBlendPixels;
        g_startupBlendPixels = nullptr;
    }

    RgbaImage img;
    if (!LoadImageRgbaFromResourceWic(hm, IDR_SPLASH_PNG, nullptr, img))
    {
        DEBUG_LOG("SplashScreen: LoadImageRgbaFromResourceWic failed for resource id=%d", IDR_SPLASH_PNG);
        return false;
    }

    DEBUG_LOG("SplashScreen: loaded embedded resource id=%d", IDR_SPLASH_PNG);
    return ApplySplashRgbaToMatrices(img);
}