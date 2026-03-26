#pragma once
#include <windows.h>
#include <stdio.h>

// ------------------------------------------------------------
// Logging configuration
// ------------------------------------------------------------

// Define whether to create a logfile for debugging
//#define CREATELOGFILE
// ------------------------------------------------------------
// Macro wrapper
// ------------------------------------------------------------

#ifdef CREATELOGFILE
#define DEBUG_LOG(...) debug_log(__VA_ARGS__)
#else
#define DEBUG_LOG(...) ((void)0)
#endif

// Base directory for logs
#define DEBUG_LOG_DIR "c:\\temp\\"

// ------------------------------------------------------------
// Logging API
// ------------------------------------------------------------

extern void debug_log(const char* format, ...);
extern void time_log(const char* arg);

// ------------------------------------------------------------
// Helper to generate a per-instance logfile name
// ------------------------------------------------------------

static inline const char* get_debug_log_path()
{
    static char path[MAX_PATH] = { 0 };

    if (path[0] != 0)
        return path;

    SYSTEMTIME st;
    GetLocalTime(&st);

    DWORD pid = GetCurrentProcessId();

    sprintf(
        path,
        "%slibusb_%04d-%02d-%02d_%02d-%02d-%02d_%lu.log",
        DEBUG_LOG_DIR,
        st.wYear,
        st.wMonth,
        st.wDay,
        st.wHour,
        st.wMinute,
        st.wSecond,
        (unsigned long)pid
    );

    return path;
}
