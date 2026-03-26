#include <windows.h>
#include "Debug.h"
#include "LibusbProxy.h"
#include "FrameHandler.h"
#include "SplashScreen.h"

// ------------------------------------------------------------------------
// DllMain: load the real libusb-1.0.orig.dll and get addresses
// Create Global data
// Also used to free libusb-1.0.orig.dll and release Global data.
// ------------------------------------------------------------------------
BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved)
{
    if (fdwReason == DLL_PROCESS_ATTACH)
    {
        DEBUG_LOG("\nDllMain: DLL_PROCESS_ATTACH called, DllMain handle: %p", DllMain);
        DEBUG_LOG("Load original libusb and connect to its addresses");
        loadOriginalLibusb();

        // Create Global Data here
        // This will start NamedPipeServer when the context is ready
        DEBUG_LOG("Filling frame matrices");
        initFrameHandler();

        DEBUG_LOG("Start splash screen");
        StartSplashScreen();

        DEBUG_LOG("NamedPipeServer NOT started in DllMain; waiting for active libusb transport");
    }
    else if (fdwReason == DLL_PROCESS_DETACH)
    {
        DEBUG_LOG("DllMain: DLL_PROCESS_DETACH called");
        StopNamedPipeServer();
        deleteOriginalLibUsb();
    }

    return TRUE;
}