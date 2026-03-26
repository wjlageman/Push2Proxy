#pragma once

#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdarg.h>
#include <stdint.h>
#include <exception>    // For std::exception
#include "FrameData.h"  // Your header that defines the LocalData class
#include "Debug.h"

extern bool ProcessPipeMessage(const char* inMessage, char* replyBuffer, size_t replyBufferSize, size_t* replySize);
extern bool StartNamedPipeServer();
extern bool EnsureNamedPipeServerStarted();
extern void StopNamedPipeServer();

#define PIPE_NAME "\\\\.\\pipe\\Push2Pipe"
#define BUFFER_SIZE 4096
