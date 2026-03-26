#pragma once

#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdarg.h>
#include <stdint.h>
#include <exception>
#include "FrameData.h"
#include "NamedPipeServer.h"
#include "FrameHandler.h"
#include "SplashScreen.h"

#define ORIGINAL_LIBUSB_DLL "libusb-1.0.original.dll"
#define LIBUSB_DLL "libusb-1.0.dll"

// ------------------------------------------------------------------------
// Function pointer types definitions using WINAPI consistently
// ------------------------------------------------------------------------
typedef int             (WINAPI* p_libusb_init)(void* ctx);
typedef int             (WINAPI* p_libusb_get_device_descriptor)(void* dev, void* desc);
typedef long long       (WINAPI* p_libusb_get_device_list)(void* ctx, void*** list);
typedef int             (WINAPI* p_libusb_release_interface)(void* dev_handle, int interface_number);
typedef void            (WINAPI* p_libusb_exit)(void* ctx);
typedef int             (WINAPI* p_libusb_bulk_transfer)(
    void* dev_handle,
    unsigned char endpoint,
    unsigned char* data,
    int length,
    int* transferred,
    unsigned int timeout
    );
typedef const char* (WINAPI* p_libusb_strerror)(int errcode);
typedef void            (WINAPI* p_libusb_close)(void* dev_handle);
typedef int             (WINAPI* p_libusb_open)(void* dev, void** dev_handle);
typedef void            (WINAPI* p_libusb_free_device_list)(void** list, int unref_devices);
typedef int             (WINAPI* p_libusb_claim_interface)(void* dev_handle, int interface_number);
typedef void* (WINAPI* p_libusb_alloc_transfer)(int iso_packets);
typedef void            (WINAPI* p_libusb_free_transfer)(void* transfer);
typedef int             (WINAPI* p_libusb_submit_transfer)(void* transfer);
typedef int             (WINAPI* p_libusb_cancel_transfer)(void* transfer);
typedef int             (WINAPI* p_libusb_handle_events_timeout)(void* ctx, void* tv);
typedef int             (WINAPI* p_libusb_set_option)(void* ctx, int option);
typedef const char* (WINAPI* p_libusb_error_name)(int errcode);
typedef int             (WINAPI* p_libusb_hotplug_deregister_callback)(void* ctx, void* callback_handle);

typedef struct _libusb_transfer
{
    void* dev_handle;
    unsigned char endpoint;
    unsigned char flags;
    unsigned char type;
    unsigned int timeout;
    int status;
    int length;
    int actual_length;
    void (*callback)(struct _libusb_transfer*);
    void* user_data;
    unsigned char* buffer;
    int num_iso_packets;
    struct libusb_iso_packet_descriptor* iso_packet_desc;
} libusb_transfer;

typedef struct libusb_device_descriptor
{
    uint8_t  bLength;
    uint8_t  bDescriptorType;
    uint16_t bcdUSB;
    uint8_t  bDeviceClass;
    uint8_t  bDeviceSubClass;
    uint8_t  bDeviceProtocol;
    uint8_t  bMaxPacketSize0;
    uint16_t idVendor;
    uint16_t idProduct;
    uint16_t bcdDevice;
    uint8_t  iManufacturer;
    uint8_t  iProduct;
    uint8_t  iSerialNumber;
    uint8_t  bNumConfigurations;
} libusb_device_descriptor;

struct libusb_device_handle
{
    int dummy;
};

// ------------------------------------------------------------------------
// Static pointers to the real functions (from the original DLL)
// ------------------------------------------------------------------------
extern p_libusb_init                        real_libusb_init;
extern p_libusb_get_device_descriptor       real_libusb_get_device_descriptor;
extern p_libusb_get_device_list             real_libusb_get_device_list;
extern p_libusb_release_interface           real_libusb_release_interface;
extern p_libusb_exit                        real_libusb_exit;
extern p_libusb_bulk_transfer               real_libusb_bulk_transfer;
extern p_libusb_strerror                    real_libusb_strerror;
extern p_libusb_close                       real_libusb_close;
extern p_libusb_open                        real_libusb_open;
extern p_libusb_free_device_list            real_libusb_free_device_list;
extern p_libusb_claim_interface             real_libusb_claim_interface;
extern p_libusb_alloc_transfer              real_libusb_alloc_transfer;
extern p_libusb_free_transfer               real_libusb_free_transfer;
extern p_libusb_submit_transfer             real_libusb_submit_transfer;
extern p_libusb_cancel_transfer             real_libusb_cancel_transfer;
extern p_libusb_handle_events_timeout       real_libusb_handle_events_timeout;
extern p_libusb_set_option                  real_libusb_set_option;
extern p_libusb_error_name                  real_libusb_error_name;
extern p_libusb_hotplug_deregister_callback real_libusb_hotplug_deregister_callback;

typedef void (*libusb_callback_t)(struct _libusb_transfer*);

extern bool newLiveFrame;

extern void* globalPush2Device;
extern void* globalPush2Handle;

extern bool loadOriginalLibusb();
extern bool deleteOriginalLibUsb();