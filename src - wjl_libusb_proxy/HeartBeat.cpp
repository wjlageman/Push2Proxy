#include "Heartbeat.h"
#include "ext.h"
#include "Debug.h"

extern "C" void proxy_notify_connection_started();

static NamedPipeClient* namedPipeClient = nullptr;
static HANDLE            thread = nullptr;
static bool              stop = false;
static DWORD             interval = 500;
static bool              connection_started_reported = false;

static DWORD WINAPI heartbeat_thread(LPVOID)
{
    pipe_heartbeat_command msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.type, "COMMAND");
    strcpy(msg.message, "Heartbeat");

    while (!stop)
    {
        if (namedPipeClient)
        {
            DWORD result = namedPipeClient->sendMessageNoReply(&msg, sizeof(msg));
            if (result > 0 && !connection_started_reported)
            {
                connection_started_reported = true;
                proxy_notify_connection_started();
            }
        }

        // Sleep for a while
        Sleep(interval);
    }
    return 0;
}

bool startHeartbeat(NamedPipeClient* client, DWORD interval_ms)
{
    if (thread) return true;     // al gestart

    namedPipeClient = client;
    interval = interval_ms ? interval_ms : 500;
    stop = false;
    thread = CreateThread(nullptr, 0, heartbeat_thread, nullptr, 0, nullptr);
    return (thread != nullptr);
}

void stopHeartbeat()
{
    if (!thread) return;

    stop = true;
    WaitForSingleObject(thread, 1000);
    CloseHandle(thread);
    thread = nullptr;
}
