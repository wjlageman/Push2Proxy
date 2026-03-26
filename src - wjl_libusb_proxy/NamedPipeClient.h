#pragma once

#include <windows.h>
#include <string>

#define IDLE_TIMEOUT 1000

// Callback type: a function that receives a reply message and its size.
typedef void (*MessageCallback)(const void* reply, DWORD replySize);

class NamedPipeClient {
public:
    // Constructor without polling: no callback is supplied.
    NamedPipeClient(const std::string& pipeName);

    // Constructor with polling: a callback is supplied along with a polling message.
    // The pollingMessage pointer points to a buffer of pollingMessageSize bytes.
    NamedPipeClient(const std::string& pipeName, MessageCallback callback, const void* pollingMessage, DWORD pollingMessageSize);

    // Destructor: stops polling thread and closes the connection.
    ~NamedPipeClient();

    // Closes the connection manually.
    void close();

    // Sends a message without waiting for a reply.
    // Returns the number of bytes written, or 0 on failure.
    DWORD sendMessageNoReply(const void* message, DWORD messageSize);

    // Sends a message and waits for a reply.
    // Returns the number of bytes read as reply, or 0 on failure.
    DWORD sendMessageWithReply(const void* message, DWORD messageSize, void* replyBuffer, DWORD replyBufferSize);

    // Returns true if the connection is open.
    bool isConnected() const;

    // Get and set the idle timeout (in milliseconds). Default is IDLE_TIMEOUT, 30000 ms.
    DWORD getIdleTimeout() const;
    void setIdleTimeout(DWORD timeout);

    // Get and set the polling rate (in milliseconds). Default is 50ms.
    DWORD getPollingRate() const;
    void setPollingRate(DWORD rate);

private:
    std::string m_pipeName;      // The pipe name.
    HANDLE m_hPipe;              // Connection handle.
    MessageCallback m_callback;  // Callback for incoming messages (if non-NULL).

    // Polling message and its size (if polling is enabled).
    char* m_pollMessage;
    DWORD m_pollMessageSize;

    // Polling thread variables.
    HANDLE m_timeoutThread;      // Handle of the polling thread.
    volatile bool m_stopPolling; // Flag to signal the polling thread to stop.

    DWORD m_idleTimeout;         // Idle timeout in ms (after last message, connection will be closed).
    DWORD m_pollingRate;         // Polling rate in ms.
    ULONGLONG m_lastMessageTime; // Timestamp (from GetTickCount64) when the last message was sent.

    CRITICAL_SECTION m_lock;     // Protects m_hPipe, m_lastMessageTime, and heartbeat/poll messages.

    // Attempts to open the connection if not already open.
    // Will try every 50ms for up to 500ms.
    // Returns true if connection is open.
    bool openConnection();

    // Updates m_lastMessageTime to the current time.
    void updateLastMessageTime();

    // Polling thread procedure.
    static DWORD WINAPI PollThreadProc(LPVOID param);
    void pollThread();
};

