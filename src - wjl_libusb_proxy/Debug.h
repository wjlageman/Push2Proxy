#pragma once

#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <stddef.h>

extern void debug_log(const char* format, ...);
extern void printHexDump(const void* data, size_t len);

// Decide whether to create a log file
//#define CREATELOGFILE
#ifdef CREATELOGFILE
#define DEBUG_LOG(...) debug_log(__VA_ARGS__)
#else
#define DEBUG_LOG(...) ((void)0)
#endif

// Base directory for log files
#define DEBUG_LOG_DIR "c:\\temp\\"

// Returns a per-process logfile path.
// Example:
// c:\temp\jit_wjl_push2_lcd_2026-03-14_14-22-31_12345.log
static inline const char* get_debug_log_path()
{
    static char path[MAX_PATH] = { 0 };

    if (path[0] != 0)
    {
        return path;
    }

    SYSTEMTIME st;
    GetLocalTime(&st);

    DWORD pid = GetCurrentProcessId();

    sprintf(
        path,
        "%swjl_libusb_proxy_%04d-%02d-%02d_%02d-%02d-%02d_%lu.log",
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
