#include "Takeover.h"

#include <windows.h>

#include "ext.h"
#include "Debug.h"
#include "NamedPipeClient.h"
#include "HeartBeat.h"

// Shared globals from jit_matrix_handler.cpp
extern NamedPipeClient* namedPipe;
extern const char* PIPE_NAME;

// Shared service lock from jit_matrix_handler.cpp
extern "C" void proxy_service_lock();
extern "C" void proxy_service_unlock();

// Existing notification functions from jit_matrix_handler.cpp
extern "C" void proxy_notify_max_editor_started();
extern "C" void proxy_notify_max_editor_ended();

static const char* TAKEOVER_EVENT_NAME = "Global\\Push2Takeover";
static const char* REACTIVATE_EVENT_NAME = "Global\\Push2Reactivate";

static HANDLE g_takeover_event = NULL;
static HANDLE g_reactivate_event = NULL;
static HANDLE g_takeover_stop_event = NULL;
static HANDLE g_takeover_thread = NULL;

static CRITICAL_SECTION g_pipe_lock;
static bool g_pipe_lock_initialized = false;

static volatile LONG g_taken_over = 0;

static DWORD WINAPI takeover_wait_thread(LPVOID lpParam)
{
    HANDLE wait_handles[3];
    wait_handles[0] = g_takeover_event;
    wait_handles[1] = g_reactivate_event;
    wait_handles[2] = g_takeover_stop_event;

    post("Takeover: wait thread started");
    DEBUG_LOG("Takeover: wait thread started");

    for (;;)
    {
        DWORD wait_result = WaitForMultipleObjects(3, wait_handles, FALSE, INFINITE);

        if (wait_result == WAIT_OBJECT_0)
        {
            post("Takeover: bang received");
            DEBUG_LOG("Takeover: bang received");

            proxy_service_lock();

            if (InterlockedCompareExchange(&g_taken_over, 0, 0) == 0)
            {
                InterlockedExchange(&g_taken_over, 1);
                post("Takeover: taken_over set to true");
                DEBUG_LOG("Takeover: taken_over set to true");

                takeover_lock_pipe();

                post("Takeover: stopHeartbeat");
                DEBUG_LOG("Takeover: stopHeartbeat");
                stopHeartbeat();

                if (namedPipe)
                {
                    post("Takeover: deleting namedPipe");
                    DEBUG_LOG("Takeover: deleting namedPipe %p", namedPipe);
                    delete namedPipe;
                    namedPipe = nullptr;
                }
                else
                {
                    post("Takeover: namedPipe already NULL");
                    DEBUG_LOG("Takeover: namedPipe already NULL");
                }

                takeover_unlock_pipe();

                proxy_notify_max_editor_started();
            }
            else
            {
                post("Takeover: bang ignored because instance is already taken over");
                DEBUG_LOG("Takeover: bang ignored because instance is already taken over");
            }

            proxy_service_unlock();
            continue;
        }

        if (wait_result == WAIT_OBJECT_0 + 1)
        {
            post("Takeover: reactivate bang received");
            DEBUG_LOG("Takeover: reactivate bang received");

            proxy_service_lock();

            if (InterlockedCompareExchange(&g_taken_over, 0, 0) != 0)
            {
                takeover_lock_pipe();

                if (!namedPipe)
                {
                    post("Takeover: recreating namedPipe");
                    DEBUG_LOG("Takeover: recreating namedPipe");
                    namedPipe = new NamedPipeClient(PIPE_NAME);
                    post("Takeover: namedPipe recreated");
                    DEBUG_LOG("Takeover: namedPipe recreated %p", namedPipe);

                    post("Takeover: restarting heartbeat");
                    DEBUG_LOG("Takeover: restarting heartbeat");
                    startHeartbeat(namedPipe, 500);
                    post("Takeover: heartbeat restarted");
                    DEBUG_LOG("Takeover: heartbeat restarted");
                }
                else
                {
                    post("Takeover: reactivate ignored because namedPipe already exists");
                    DEBUG_LOG("Takeover: reactivate ignored because namedPipe already exists %p", namedPipe);
                }

                takeover_unlock_pipe();

                InterlockedExchange(&g_taken_over, 0);
                post("Takeover: taken_over reset to false");
                DEBUG_LOG("Takeover: taken_over reset to false");

                proxy_notify_max_editor_ended();
            }
            else
            {
                post("Takeover: reactivate ignored because instance is already active");
                DEBUG_LOG("Takeover: reactivate ignored because instance is already active");
            }

            proxy_service_unlock();
            continue;
        }

        if (wait_result == WAIT_OBJECT_0 + 2)
        {
            post("Takeover: stop event received");
            DEBUG_LOG("Takeover: stop event received");
            return 0;
        }

        post("Takeover: WaitForMultipleObjects failed");
        DEBUG_LOG("Takeover: WaitForMultipleObjects failed");
        Sleep(10);
    }
}

void takeover_init()
{
    if (!g_pipe_lock_initialized)
    {
        InitializeCriticalSection(&g_pipe_lock);
        g_pipe_lock_initialized = true;
        post("Takeover: pipe lock initialized");
        DEBUG_LOG("Takeover: pipe lock initialized");
    }

    InterlockedExchange(&g_taken_over, 0);
    post("Takeover: init complete, taken_over reset");
    DEBUG_LOG("Takeover: init complete, taken_over reset");
}

void takeover_free()
{
    post("Takeover: free");
    DEBUG_LOG("Takeover: free");

    takeover_stop_listener();

    if (g_pipe_lock_initialized)
    {
        DeleteCriticalSection(&g_pipe_lock);
        g_pipe_lock_initialized = false;
        post("Takeover: pipe lock freed");
        DEBUG_LOG("Takeover: pipe lock freed");
    }
}

void takeover_send_bang()
{
    HANDLE h_event = CreateEventA(
        NULL,
        FALSE,
        FALSE,
        TAKEOVER_EVENT_NAME
    );

    if (!h_event)
    {
        post("Takeover: CreateEventA failed in takeover_send_bang");
        DEBUG_LOG("Takeover: CreateEventA failed in takeover_send_bang");
        return;
    }

    if (!SetEvent(h_event))
    {
        post("Takeover: SetEvent failed in takeover_send_bang");
        DEBUG_LOG("Takeover: SetEvent failed in takeover_send_bang");
    }
    else
    {
        post("Takeover: bang sent");
        DEBUG_LOG("Takeover: bang sent");
    }

    CloseHandle(h_event);
}

void takeover_send_reactivate_bang()
{
    HANDLE h_event = CreateEventA(
        NULL,
        FALSE,
        FALSE,
        REACTIVATE_EVENT_NAME
    );

    if (!h_event)
    {
        post("Takeover: CreateEventA failed in takeover_send_reactivate_bang");
        DEBUG_LOG("Takeover: CreateEventA failed in takeover_send_reactivate_bang");
        return;
    }

    if (!SetEvent(h_event))
    {
        post("Takeover: SetEvent failed in takeover_send_reactivate_bang");
        DEBUG_LOG("Takeover: SetEvent failed in takeover_send_reactivate_bang");
    }
    else
    {
        post("Takeover: reactivate bang sent");
        DEBUG_LOG("Takeover: reactivate bang sent");
    }

    CloseHandle(h_event);
}

void takeover_start_listener()
{
    if (g_takeover_thread)
    {
        post("Takeover: listener already started");
        DEBUG_LOG("Takeover: listener already started");
        return;
    }

    g_takeover_event = CreateEventA(
        NULL,
        FALSE,
        FALSE,
        TAKEOVER_EVENT_NAME
    );

    if (!g_takeover_event)
    {
        post("Takeover: CreateEventA failed for takeover event");
        DEBUG_LOG("Takeover: CreateEventA failed for takeover event");
        return;
    }

    g_reactivate_event = CreateEventA(
        NULL,
        FALSE,
        FALSE,
        REACTIVATE_EVENT_NAME
    );

    if (!g_reactivate_event)
    {
        post("Takeover: CreateEventA failed for reactivate event");
        DEBUG_LOG("Takeover: CreateEventA failed for reactivate event");
        CloseHandle(g_takeover_event);
        g_takeover_event = NULL;
        return;
    }

    g_takeover_stop_event = CreateEventA(
        NULL,
        TRUE,
        FALSE,
        NULL
    );

    if (!g_takeover_stop_event)
    {
        post("Takeover: CreateEventA failed for stop event");
        DEBUG_LOG("Takeover: CreateEventA failed for stop event");
        CloseHandle(g_reactivate_event);
        g_reactivate_event = NULL;

        CloseHandle(g_takeover_event);
        g_takeover_event = NULL;
        return;
    }

    g_takeover_thread = CreateThread(
        NULL,
        0,
        takeover_wait_thread,
        NULL,
        0,
        NULL
    );

    if (!g_takeover_thread)
    {
        post("Takeover: CreateThread failed");
        DEBUG_LOG("Takeover: CreateThread failed");

        CloseHandle(g_takeover_stop_event);
        g_takeover_stop_event = NULL;

        CloseHandle(g_reactivate_event);
        g_reactivate_event = NULL;

        CloseHandle(g_takeover_event);
        g_takeover_event = NULL;
        return;
    }

    post("Takeover: listener started");
    DEBUG_LOG("Takeover: listener started");
}

void takeover_stop_listener()
{
    if (g_takeover_thread || g_takeover_event || g_reactivate_event || g_takeover_stop_event)
    {
        post("Takeover: stopping listener");
        DEBUG_LOG("Takeover: stopping listener");
    }

    if (g_takeover_stop_event)
    {
        SetEvent(g_takeover_stop_event);
    }

    if (g_takeover_thread)
    {
        WaitForSingleObject(g_takeover_thread, 1000);
        CloseHandle(g_takeover_thread);
        g_takeover_thread = NULL;
    }

    if (g_takeover_stop_event)
    {
        CloseHandle(g_takeover_stop_event);
        g_takeover_stop_event = NULL;
    }

    if (g_reactivate_event)
    {
        CloseHandle(g_reactivate_event);
        g_reactivate_event = NULL;
    }

    if (g_takeover_event)
    {
        CloseHandle(g_takeover_event);
        g_takeover_event = NULL;
    }

    post("Takeover: listener stopped");
    DEBUG_LOG("Takeover: listener stopped");
}

bool takeover_is_taken_over()
{
    return InterlockedCompareExchange(&g_taken_over, 0, 0) != 0;
}

void takeover_lock_pipe()
{
    if (g_pipe_lock_initialized)
    {
        EnterCriticalSection(&g_pipe_lock);
    }
}

void takeover_unlock_pipe()
{
    if (g_pipe_lock_initialized)
    {
        LeaveCriticalSection(&g_pipe_lock);
    }
}