#include "WicPngLoader.h"

#include <wincodec.h>
#include <combaseapi.h>
#include <objidl.h>
#include <cstring>

#pragma comment(lib, "windowscodecs.lib")

static void SafeRelease(IUnknown* p)
{
    if (p)
    {
        p->Release();
    }
}

static bool EnsureComInitialized(bool& didInit)
{
    didInit = false;

    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (SUCCEEDED(hr))
    {
        didInit = true;
        return true;
    }

    if (hr == RPC_E_CHANGED_MODE)
    {
        // COM was initialized elsewhere with a different threading model.
        // We can proceed, but we must not call CoUninitialize() in this case.
        didInit = false;
        return true;
    }

    return false;
}

static bool CreateWicFactory(IWICImagingFactory** outFactory)
{
    *outFactory = nullptr;

    IWICImagingFactory* factory = nullptr;
    HRESULT hr = CoCreateInstance(
        CLSID_WICImagingFactory,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&factory));

    if (FAILED(hr) || !factory)
    {
        return false;
    }

    *outFactory = factory;
    return true;
}

static bool DecodeWicBitmapToRgba8(IWICImagingFactory* factory, IWICBitmapSource* source, RgbaImage& out)
{
    IWICFormatConverter* converter = nullptr;

    HRESULT hr = factory->CreateFormatConverter(&converter);
    if (FAILED(hr) || !converter)
    {
        return false;
    }

    hr = converter->Initialize(
        source,
        GUID_WICPixelFormat32bppRGBA,
        WICBitmapDitherTypeNone,
        nullptr,
        0.0,
        WICBitmapPaletteTypeCustom);

    if (FAILED(hr))
    {
        SafeRelease(converter);
        return false;
    }

    UINT w = 0;
    UINT h = 0;
    hr = converter->GetSize(&w, &h);
    if (FAILED(hr) || w == 0 || h == 0)
    {
        SafeRelease(converter);
        return false;
    }

    out.width = static_cast<int>(w);
    out.height = static_cast<int>(h);
    out.rgba.assign(static_cast<size_t>(w) * static_cast<size_t>(h) * 4, 0);

    const UINT stride = w * 4;
    const UINT bufSize = static_cast<UINT>(out.rgba.size());

    hr = converter->CopyPixels(nullptr, stride, bufSize, out.rgba.data());

    SafeRelease(converter);
    return SUCCEEDED(hr);
}

bool LoadImageRgbaFromFileWic(const wchar_t* path, RgbaImage& out)
{
    out = RgbaImage{};

    bool didInit = false;
    if (!EnsureComInitialized(didInit))
    {
        return false;
    }

    IWICImagingFactory* factory = nullptr;
    if (!CreateWicFactory(&factory))
    {
        if (didInit) { CoUninitialize(); }
        return false;
    }

    IWICBitmapDecoder* decoder = nullptr;
    HRESULT hr = factory->CreateDecoderFromFilename(
        path,
        nullptr,
        GENERIC_READ,
        WICDecodeMetadataCacheOnLoad,
        &decoder);

    if (FAILED(hr) || !decoder)
    {
        SafeRelease(factory);
        if (didInit) { CoUninitialize(); }
        return false;
    }

    IWICBitmapFrameDecode* frame = nullptr;
    hr = decoder->GetFrame(0, &frame);
    if (FAILED(hr) || !frame)
    {
        SafeRelease(decoder);
        SafeRelease(factory);
        if (didInit) { CoUninitialize(); }
        return false;
    }

    const bool ok = DecodeWicBitmapToRgba8(factory, frame, out);

    SafeRelease(frame);
    SafeRelease(decoder);
    SafeRelease(factory);

    if (didInit) { CoUninitialize(); }
    return ok;
}

static bool DecodeWicStreamToRgba8(IWICImagingFactory* factory, IStream* stream, RgbaImage& out)
{
    IWICBitmapDecoder* decoder = nullptr;
    HRESULT hr = factory->CreateDecoderFromStream(
        stream,
        nullptr,
        WICDecodeMetadataCacheOnLoad,
        &decoder);

    if (FAILED(hr) || !decoder)
    {
        return false;
    }

    IWICBitmapFrameDecode* frame = nullptr;
    hr = decoder->GetFrame(0, &frame);
    if (FAILED(hr) || !frame)
    {
        SafeRelease(decoder);
        return false;
    }

    const bool ok = DecodeWicBitmapToRgba8(factory, frame, out);

    SafeRelease(frame);
    SafeRelease(decoder);
    return ok;
}

bool LoadImageRgbaFromResourceWic(HMODULE module, int resourceId, LPCWSTR resourceType, RgbaImage& out)
{
    out = RgbaImage{};

    if (!module)
    {
        return false;
    }

    if (!resourceType)
    {
        // RT_RCDATA is defined as an ANSI pointer type in some headers.
        // Use a wide MAKEINTRESOURCEW value to call FindResourceW reliably.
        resourceType = MAKEINTRESOURCEW(10); // RT_RCDATA
    }

    HRSRC hRes = FindResourceW(module, MAKEINTRESOURCEW(resourceId), resourceType);
    if (!hRes)
    {
        return false;
    }

    const DWORD size = SizeofResource(module, hRes);
    if (size == 0)
    {
        return false;
    }

    HGLOBAL hData = LoadResource(module, hRes);
    if (!hData)
    {
        return false;
    }

    const void* pData = LockResource(hData);
    if (!pData)
    {
        return false;
    }

    // WIC expects a seekable stream. Copy the bytes into an HGLOBAL-backed IStream.
    HGLOBAL hCopy = GlobalAlloc(GMEM_MOVEABLE, size);
    if (!hCopy)
    {
        return false;
    }

    void* pCopy = GlobalLock(hCopy);
    if (!pCopy)
    {
        GlobalFree(hCopy);
        return false;
    }

    memcpy(pCopy, pData, size);
    GlobalUnlock(hCopy);

    IStream* stream = nullptr;
    HRESULT hr = CreateStreamOnHGlobal(hCopy, TRUE, &stream);
    if (FAILED(hr) || !stream)
    {
        GlobalFree(hCopy);
        return false;
    }

    bool didInit = false;
    if (!EnsureComInitialized(didInit))
    {
        SafeRelease(stream);
        return false;
    }

    IWICImagingFactory* factory = nullptr;
    if (!CreateWicFactory(&factory))
    {
        SafeRelease(stream);
        if (didInit) { CoUninitialize(); }
        return false;
    }

    const bool ok = DecodeWicStreamToRgba8(factory, stream, out);

    SafeRelease(factory);
    SafeRelease(stream);

    if (didInit) { CoUninitialize(); }
    return ok;
}
