#pragma once

#include <windows.h>

void StartSplashScreen();
void EnsureFadeTimerStarted();

// Cache the last Live frame so the splash fade can emit extra frames.
void CacheLastLiveFrame(const unsigned char* buffer, int length);