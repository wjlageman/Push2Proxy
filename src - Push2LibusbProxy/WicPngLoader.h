#pragma once

#include <cstdint>
#include <vector>
#include <windows.h>

struct RgbaImage
{
    int width = 0;
    int height = 0;
    std::vector<std::uint8_t> rgba; // width * height * 4
};

// Loads an image using Windows Imaging Component (WIC) and converts it to RGBA8.
// Returns true on success.
bool LoadImageRgbaFromFileWic(const wchar_t* path, RgbaImage& out);

// Loads an image from a Win32 resource using WIC and converts it to RGBA8.
// resourceType is typically RCDATA (pass nullptr to use the default).
// Returns true on success.
bool LoadImageRgbaFromResourceWic(HMODULE module, int resourceId, LPCWSTR resourceType, RgbaImage& out);
