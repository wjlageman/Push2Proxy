#include "NamedPipeServer.h"
#include "Push2Matrix.h"
#include "RGB.h"
#include "BlendPixel.h"
#include "PipeMessageStructures.h"

HANDLE hPipeThread = NULL;
HANDLE hStopEvent = NULL;

static const wchar_t* kServerMutexName = L"Global\\Push2LcdPipeServerMutex";
static volatile LONG g_pipe_server_started = 0;

extern void shutdownExistingNamedPipeServer();

extern CRITICAL_SECTION g_displayLock;
extern Push2Matrix<RGB>* livePixels;
extern Push2Matrix<RGB>* maxPixels;
extern Push2Matrix<BlendPixel>* blendPixels;

DWORD WINAPI NamedPipeServerThread(LPVOID lpParam)
{
    // Create a shutdownmessage
    char shutdownMsg[80];
    sprintf(shutdownMsg, "Shutdown '%s'", PIPE_NAME);

    // Time measuring
    LARGE_INTEGER start, end, freq;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    DEBUG_LOG("{LIBUSB} STARTING NEW NamedPipeServerThread");

    // === Single-instance guard ===
    HANDLE hMutex = CreateMutexW(NULL, FALSE, kServerMutexName);
    if (!hMutex) {
        DEBUG_LOG("{LIBUSB} CreateMutex failed: %lu", GetLastError());
        return 0;
    }
    DWORD wait = WaitForSingleObject(hMutex, 0);
    if (wait == WAIT_TIMEOUT) {
        shutdownExistingNamedPipeServer();
        DEBUG_LOG("{LIBUSB} Back from shutdownExistingNamedPipeServer");
        wait = WaitForSingleObject(hMutex, 2000);
    }
    if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED) {
        DEBUG_LOG("{LIBUSB} Could not acquire server mutex (wait=%lu)", wait);
        CloseHandle(hMutex);
        return 0;
    }

    DEBUG_LOG("{LIBUSB} Start a new Named Pipe server");
    const DWORD bufferSize = BUFFER_SIZE;
    char inBuffer[bufferSize] = { 0 };
    char outBuffer[bufferSize] = { 0 };
    DWORD bytesRead = 0;
    BOOL  fSuccess = FALSE;

    // --- Create ONE pipe instance and reuse it for all clients ---
    HANDLE hPipe = CreateNamedPipeA(
        PIPE_NAME,
        PIPE_ACCESS_DUPLEX,                                   // R/W
        PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,// message mode, blocking
        PIPE_UNLIMITED_INSTANCES,
        bufferSize, bufferSize,
        0,                                                    // default timeout
        NULL                                                  // default security
    );
    if (hPipe == INVALID_HANDLE_VALUE) {
        DEBUG_LOG("{LIBUSB} CreateNamedPipe failed, error %lu", GetLastError());
        CloseHandle(hMutex);
        return 0;
    }

    DEBUG_LOG("{LIBUSB} A new Named Pipe server thread started. Waiting for connections...");

    bool mustShutdown = false;
    while (!mustShutdown)
    {
        QueryPerformanceCounter(&end);
        double elapsedMs = static_cast<double>(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
        DEBUG_LOG("{LIBUSB} Waiting for a client to connect. Time %f ms", elapsedMs);
        QueryPerformanceCounter(&start);

        // Wait for client (handle case client already connected)
        fSuccess = ConnectNamedPipe(hPipe, NULL) ? TRUE : (GetLastError() == ERROR_PIPE_CONNECTED);
        if (!fSuccess) {
            DWORD ce = GetLastError();
            DEBUG_LOG("{LIBUSB} ConnectNamedPipe failed, error %lu", ce);
            // Try again after a brief pause rather than recreating the pipe
            Sleep(1);
            continue;
        }

        QueryPerformanceCounter(&end);
        elapsedMs = static_cast<double>(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
        DEBUG_LOG("Client connected in %f ms", elapsedMs);
        QueryPerformanceCounter(&start);

        // ---- Per-client I/O loop ----
        for (;;)
        {
            memset(inBuffer, 0, sizeof(inBuffer));
            SetLastError(0);
            bytesRead = 0;
            fSuccess = ReadFile(hPipe, inBuffer, bufferSize - 1, &bytesRead, NULL);
            DWORD err = GetLastError();
            DEBUG_LOG("Received pipe msg bytesRead: %lu", bytesRead);

            if (!fSuccess) {
                if (err == ERROR_BROKEN_PIPE) {
                    DEBUG_LOG("{LIBUSB} Client disconnected (ERROR_BROKEN_PIPE).");
                }
                else {
                    DEBUG_LOG("{LIBUSB} ReadFile failed, error %lu", err);
                }
                break; // leave per-client loop → disconnect & wait next client
            }
            if (bytesRead == 0) {
                // no payload; avoid busy spin
                Sleep(1);
                continue;
            }

            // Shutdown?
            if (strncmp(inBuffer, shutdownMsg, strlen(shutdownMsg)) == 0) {
                DEBUG_LOG("{LIBUSB} Shutdown message received. Closing server.");
                mustShutdown = true;
                break;
            }

            // Process message
            size_t replySize = 0;
            size_t bigReplySize = sizeof(pipe_frame_transfer);
            char* bigReplyBuffer = (char*)malloc(bigReplySize);
            if (!bigReplyBuffer) {
                DEBUG_LOG("{LIBUSB} malloc failed for bigReplyBuffer");
                // Signal failure to client? Here we just break client loop.
                break;
            }

            ProcessPipeMessage(inBuffer, bigReplyBuffer, bigReplySize, &replySize);

            if (replySize > 0) {
                DWORD wrote = 0;
                if (!WriteFile(hPipe, bigReplyBuffer, (DWORD)replySize, &wrote, NULL)) {
                    DEBUG_LOG("{LIBUSB} WriteFile failed, error %lu", GetLastError());
                    free(bigReplyBuffer);
                    break;
                }
            }
            free(bigReplyBuffer);

            QueryPerformanceCounter(&end);
            double loopMs = static_cast<double>(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
            DEBUG_LOG("Server loop took %f ms", loopMs);
            QueryPerformanceCounter(&start);
        }

        // Disconnect current client, but KEEP the same pipe handle for the next one
        DisconnectNamedPipe(hPipe);

        if (!mustShutdown) {
            DEBUG_LOG("{LIBUSB} Disconnected client. Waiting for new connection...");
        }
    }

    // Cleanup once on shutdown
    CloseHandle(hPipe);
    CloseHandle(hMutex);
    DEBUG_LOG("{LIBUSB} Named Pipe server thread shutting down.");
    return 0;
}

// Add this helper (same TU as shutdownExistingNamedPipeServer)
static bool wait_until_old_server_gone(DWORD timeout_ms)
{
    DEBUG_LOG("{LIBUSB} In wait_until_old_server_gone");
    const DWORD deadline = GetTickCount() + timeout_ms;
    for (;;)
    {
        // If there's NO server, WaitNamedPipe fails with ERROR_FILE_NOT_FOUND.
        if (!WaitNamedPipeA(PIPE_NAME, 200)) {
            DWORD e = GetLastError();
            if (e == ERROR_FILE_NOT_FOUND) return true; // old server is gone
            // other errors -> brief backoff and retry
            Sleep(5);
        }
        else {
            // There IS a server (and at least one instance available).
            // Give it a moment to finish shutting down.
            Sleep(5);
        }
        if (GetTickCount() - deadline >= 0) return false; // timed out
    }
    DEBUG_LOG("{LIBUSB} Leaving wait_until_old_server_gone");
}

void shutdownExistingNamedPipeServer()
{
    DEBUG_LOG("{LIBUSB} In shutdownExistingNamedPipeServer");
    HANDLE hExisting = CreateFileA(PIPE_NAME, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (hExisting != INVALID_HANDLE_VALUE)
    {
        char shutdownMsg[80];
        sprintf(shutdownMsg, "Shutdown '%s'", PIPE_NAME);
        DWORD wrote = 0;
        if (WriteFile(hExisting, shutdownMsg, (DWORD)strlen(shutdownMsg), &wrote, NULL)) {
            DEBUG_LOG("{LIBUSB} Shutdown command sent, waiting for old instance to close...");
            wait_until_old_server_gone(3000);
        }
        else {
            DEBUG_LOG("{LIBUSB} WriteFile(shutdown) failed: %lu", GetLastError());
        }
        CloseHandle(hExisting);
    }
    else {
        DEBUG_LOG("{LIBUSB} No existing server to shut down (CreateFile failed: %lu)", GetLastError());
    }
}

bool StartNamedPipeServer()
{
    DEBUG_LOG("{LIBUSB} In StartNamedPipeServer");

    if (hPipeThread)
    {
        DEBUG_LOG("{LIBUSB} hPipeThread already set");
        return true;
    }

    // Create shutdown event
    hStopEvent = CreateEvent(NULL, TRUE, FALSE, NULL);
    if (!hStopEvent)
    {
        DEBUG_LOG("{LIBUSB} Failed to create hStopEvent. Error: %d", GetLastError());
        return false;
    }

    // Create and start the pipe server thread
    hPipeThread = CreateThread(NULL, 0, NamedPipeServerThread, NULL, 0, NULL);
    if (!hPipeThread)
    {
        DEBUG_LOG("{LIBUSB} Failed to create pipe server thread. Error: %d", GetLastError());
        CloseHandle(hStopEvent);
        hStopEvent = NULL;
        return false;
    }

    DEBUG_LOG("{LIBUSB} Named Pipe Server Thread started, handle %p", hPipeThread);
    return true;
}

bool EnsureNamedPipeServerStarted()
{
    if (InterlockedCompareExchange(&g_pipe_server_started, 1, 0) != 0)
    {
        DEBUG_LOG("{LIBUSB} EnsureNamedPipeServerStarted: already started");
        return true;
    }

    DEBUG_LOG("{LIBUSB} EnsureNamedPipeServerStarted: starting server now");
    if (!StartNamedPipeServer())
    {
        InterlockedExchange(&g_pipe_server_started, 0);
        return false;
    }

    return true;
}

void StopNamedPipeServer()
{
    DEBUG_LOG("{LIBUSB} In StopNamedPipeServer");

    shutdownExistingNamedPipeServer();

    if (hPipeThread)
    {
        CloseHandle(hPipeThread);
        hPipeThread = NULL;
    }

    if (hStopEvent)
    {
        CloseHandle(hStopEvent);
        hStopEvent = NULL;
    }

    InterlockedExchange(&g_pipe_server_started, 0);

    DEBUG_LOG("{LIBUSB} StopNamedPipeServer done");
}
