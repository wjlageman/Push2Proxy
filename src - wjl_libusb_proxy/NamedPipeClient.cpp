#include <windows.h>
#include <stdio.h>
#include <string.h>
// From the C74 SDK version 6
#include "ext.h"  // For post(), pipe_log() etc.
#include "Debug.h"

#include "NamedPipeClient.h"
#include "PipeMessagesStructures.h"


// Constructor without polling
NamedPipeClient::NamedPipeClient(const std::string& pipeName)
    : m_pipeName(pipeName), m_hPipe(INVALID_HANDLE_VALUE), m_callback(NULL),
    m_timeoutThread(NULL), m_stopPolling(false), m_idleTimeout(IDLE_TIMEOUT), m_pollingRate(50), m_lastMessageTime(0),
    m_pollMessage(NULL), m_pollMessageSize(0)
{
    //post("In NamedPipeClient constructor '%s'", m_pipeName.c_str());
    DEBUG_LOG("In NamedPipeClient constructor '%s'", m_pipeName.c_str());

    InitializeCriticalSection(&m_lock);
}

// Destructor: stops polling thread and closes connection.
NamedPipeClient::~NamedPipeClient()
{
    //post("In ~NamedPipeClient for pipe '%s'", m_pipeName.c_str());
    DEBUG_LOG("In ~NamedPipeClient for pipe '%s'", m_pipeName.c_str());
    // Signal polling thread to stop.
    m_stopPolling = true;
    if (m_timeoutThread) {
        WaitForSingleObject(m_timeoutThread, 2000);
        CloseHandle(m_timeoutThread);
        m_timeoutThread = NULL;
    }
    // Close connection if open.
    close();
    // Free the polling message if allocated.
    if (m_pollMessage) {
        delete[] m_pollMessage;
        m_pollMessage = NULL;
        m_pollMessageSize = 0;
    }
    DeleteCriticalSection(&m_lock);
    DEBUG_LOG("~NamedPipeClient returns");
}

// Closes the connection explicitly.
void NamedPipeClient::close()
{
    //post("Closing NamedPipeClient");
    DEBUG_LOG("Closing NamedPipeClient");
    EnterCriticalSection(&m_lock);
    if (m_hPipe != INVALID_HANDLE_VALUE) {
        CloseHandle(m_hPipe);
        m_hPipe = INVALID_HANDLE_VALUE;
        //post("NamedPipeClient: Connection closed.");
        DEBUG_LOG("NamedPipeClient: Connection closed.");
    }
    LeaveCriticalSection(&m_lock);
}

// Returns true if connection is open.
bool NamedPipeClient::isConnected() const
{
    return (m_hPipe != INVALID_HANDLE_VALUE);
}

// Updates the last message time.
void NamedPipeClient::updateLastMessageTime()
{
    m_lastMessageTime = GetTickCount64();
}

// Attempts to open the connection if not already open.
// Retries every 5 ms for up to 500 ms.
bool NamedPipeClient::openConnection()
{
    EnterCriticalSection(&m_lock);
    
    // Als we al een handle hebben: verifieer dat de verbinding nog leeft.
    if (m_hPipe != INVALID_HANDLE_VALUE) {
        DWORD avail = 0;
        if (PeekNamedPipe(m_hPipe, NULL, 0, NULL, &avail, NULL)) {
            // Server is er nog; verbinding is oké.
            LeaveCriticalSection(&m_lock);
            return true;
        }
        else {
            // Broken/closed → netjes sluiten en opnieuw proberen te openen.
            CloseHandle(m_hPipe);
            m_hPipe = INVALID_HANDLE_VALUE;
        }
    }

    const int maxAttempts = 100;
    for (int attempt = 0; attempt < maxAttempts && m_hPipe == INVALID_HANDLE_VALUE; ++attempt) {

        m_hPipe = CreateFileA(
            m_pipeName.c_str(),
            GENERIC_READ | GENERIC_WRITE,
            0,                // no sharing
            NULL,             // default security
            OPEN_EXISTING,
            0,                // default flags (synchronous)
            NULL
        );

        if (m_hPipe != INVALID_HANDLE_VALUE) {
            // Optioneel maar netjes in message-mode clients:
            DWORD mode = PIPE_READMODE_MESSAGE;
            SetNamedPipeHandleState(m_hPipe, &mode, NULL, NULL);

            updateLastMessageTime();
            LeaveCriticalSection(&m_lock);
            return true;
        }

        DWORD err = GetLastError();
        if (err == ERROR_PIPE_BUSY) {
            // Korte, begrensde wait; vermijd grote haperingen
            WaitNamedPipeA(m_pipeName.c_str(), 100);
        }
        else {
            // Server nog niet beschikbaar (bijv. ERROR_FILE_NOT_FOUND) of andere race:
            Sleep(5);
        }
    }

    LeaveCriticalSection(&m_lock);
    return false;
}

// Sends a message without waiting for a reply.
DWORD NamedPipeClient::sendMessageNoReply(const void* message, DWORD messageSize)
{
    if (!openConnection())
    {
        return 0;
    }

    EnterCriticalSection(&m_lock);
    DWORD bytesWritten = 0;
    BOOL success = WriteFile(m_hPipe, message, messageSize, &bytesWritten, NULL);
    if (!success) {
        post("NamedPipeClient: WriteFile failed, error %d", GetLastError());
        DEBUG_LOG("NamedPipeClient: WriteFile failed, error %d", GetLastError());
        LeaveCriticalSection(&m_lock);
        return 0;
    }
    updateLastMessageTime();
    LeaveCriticalSection(&m_lock);
    return bytesWritten;
}

// Send a message and waits for a reply.
DWORD NamedPipeClient::sendMessageWithReply(const void* message, DWORD messageSize,
    void* replyBuffer, DWORD replyBufferSize)
{
    LARGE_INTEGER begin, end, freq;
    QueryPerformanceFrequency(&freq);

    QueryPerformanceCounter(&begin);
    const DWORD timeoutMs = 1000; // Timeout 1000 ms
    if (!openConnection())
    {
        post("Could not open named pipe connection");
        return 0;
    }
    QueryPerformanceCounter(&end);

    EnterCriticalSection(&m_lock);

    DWORD bytesWritten = 0;
    if (!WriteFile(m_hPipe, message, messageSize, &bytesWritten, NULL)) {
        LeaveCriticalSection(&m_lock);
        return 0;
    }
    QueryPerformanceCounter(&end);
    double elapsedMs2 = static_cast<double>(end.QuadPart - begin.QuadPart) * 1000 / freq.QuadPart;
    //post("jit_matrix_input: pipe message send in %f ms", elapsedMs2);

    FlushFileBuffers(m_hPipe);       // laat server het bericht direct zien
    updateLastMessageTime();
    QueryPerformanceCounter(&end);
    elapsedMs2 = static_cast<double>(end.QuadPart - begin.QuadPart) * 1000 / freq.QuadPart;
    //post("jit_matrix_input: pipe message flushed in %f ms", elapsedMs2);

    
    ULONGLONG start = GetTickCount64();
    
    // Timeout-wachtlus until data available
    QueryPerformanceCounter(&begin);
    for (;;) {
        DWORD avail = 0;
        if (!PeekNamedPipe(m_hPipe, NULL, 0, NULL, &avail, NULL)) {
            LeaveCriticalSection(&m_lock);
            return 0;                // pipe nroken
        }
        if (avail > 0) break;        // we got data
        if (GetTickCount64() - start >= timeoutMs) {
            LeaveCriticalSection(&m_lock);
            return 0;                // timeout, no reply
        }
        Sleep(1);
    }
    QueryPerformanceCounter(&end);
    elapsedMs2 = static_cast<double>(end.QuadPart - begin.QuadPart) * 1000 / freq.QuadPart;
    //post("jit_matrix_input: pipe message waited for reply ready in %f ms", elapsedMs2);

    QueryPerformanceCounter(&begin);
    DWORD total = 0;
    for (;;) {
        DWORD avail = 0;
        if (!PeekNamedPipe(m_hPipe, NULL, 0, NULL, &avail, NULL)) {
            LeaveCriticalSection(&m_lock);
            return 0;
        }
        if (avail == 0) break;       // geen extra data meer

        DWORD space = (replyBufferSize > total) ? (replyBufferSize - total) : 0;
        if (space == 0) break;       // buffer vol, trunceren

        DWORD chunk = (avail < space) ? avail : space;
        DWORD justRead = 0;
        if (!ReadFile(m_hPipe, (char*)replyBuffer + total, chunk, &justRead, NULL)) {
            LeaveCriticalSection(&m_lock);
            return 0;
        }
        total += justRead;

        // Optioneel: kleine pauze om rest binnen te laten stromen
        //Sleep(1);
        if (GetTickCount64() - start >= timeoutMs + 50) break; // hard cap
    }
    QueryPerformanceCounter(&end);
    elapsedMs2 = static_cast<double>(end.QuadPart - begin.QuadPart) * 1000 / freq.QuadPart;
    //post("jit_matrix_input: pipe reply fetched in %f ms", elapsedMs2);

    LeaveCriticalSection(&m_lock);
    return total;
}
