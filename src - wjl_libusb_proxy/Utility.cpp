#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include <ctype.h>

#include "Debug.h"

// From the C74 SDK version 6
#include "ext.h"

// Utility to print to a per-instance logfile in c:\temp
void debug_log(const char* format, ...)
{
    const char* logfile = get_debug_log_path();

    FILE* fp = fopen(logfile, "a");
    if (!fp)
    {
        return;
    }

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
        (unsigned long)pid,
        (unsigned long)tid
    );

    va_list args;
    va_start(args, format);
    vfprintf(fp, format, args);
    va_end(args);

    fprintf(fp, "\n");
    fclose(fp);
}

// Hex dump function for debugging using post and debug_log
void printHexDump(const void* data, size_t len)
{
    const unsigned char* bytes = (const unsigned char*)data;
    char line[256];

    for (size_t i = 0; i < len; i += 16)
    {
        int offset = sprintf(line, "%08zx: ", i);

        // Print up to 16 bytes in hex
        for (size_t j = 0; j < 16; j++)
        {
            if (i + j < len)
            {
                offset += sprintf(line + offset, "%02X ", bytes[i + j]);
            }
            else
            {
                offset += sprintf(line + offset, "   ");
            }
        }

        // Append the ASCII characters
        offset += sprintf(line + offset, " |");

        for (size_t j = 0; j < 16; j++)
        {
            if (i + j < len)
            {
                unsigned char c = bytes[i + j];
                offset += sprintf(line + offset, "%c", isprint(c) ? c : '.');
            }
        }

        sprintf(line + offset, "|");

        post("%s", line);
        DEBUG_LOG("%s", line);
    }
}