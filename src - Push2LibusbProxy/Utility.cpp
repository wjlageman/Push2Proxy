#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdarg.h>
#include <stdint.h>

#include "Debug.h"

// ------------------------------------------------------------
// Logging implementation
// ------------------------------------------------------------

void debug_log(const char* format, ...)
{
#ifdef CREATELOGFILE

    const char* logfile = get_debug_log_path();

    FILE* fp = fopen(logfile, "a");
    if (!fp)
        return;

    SYSTEMTIME st;
    GetLocalTime(&st);

    DWORD pid = GetCurrentProcessId();
    DWORD tid = GetCurrentThreadId();

    fprintf(
        fp,
        "[%04d-%02d-%02d %02d:%02d:%02d.%03d pid=%lu tid=%lu] ",
        st.wYear,
        st.wMonth,
        st.wDay,
        st.wHour,
        st.wMinute,
        st.wSecond,
        st.wMilliseconds,
        pid,
        tid
    );

    va_list args;
    va_start(args, format);
    vfprintf(fp, format, args);
    va_end(args);

    fprintf(fp, "\n");

    fclose(fp);

#endif
}

// ------------------------------------------------------------
// time_log helper
// ------------------------------------------------------------

void time_log(const char* arg)
{
#ifdef CREATELOGFILE

    static LARGE_INTEGER freq;
    static LARGE_INTEGER start;
    static int initialized = 0;

    if (!initialized)
    {
        QueryPerformanceFrequency(&freq);
        initialized = 1;
    }

    if (arg && strcmp(arg, "start") == 0)
    {
        QueryPerformanceCounter(&start);
        return;
    }

    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);

    double ms =
        (double)(now.QuadPart - start.QuadPart) * 1000.0 /
        (double)freq.QuadPart;

    debug_log("TIME: %.3f ms", ms);

#endif
}