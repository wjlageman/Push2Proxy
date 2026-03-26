#include <windows.h>
#include <stdio.h>
#include <exception>
#include <math.h>
#include <cstdint>
#include <string.h>

// From the C74 SDK version 6
#include "ext.h"
#include "ext_obex.h"
#include "jit.common.h"
#include "max.jit.mop.h"

#include "Debug.h"
#include "wjl_libusb_proxy.h"
#include "NamedPipeClient.h"
#include "PipeMessagesStructures.h"
#include "HeartBeat.h"
#include "Takeover.h"

const char* MAX_EXTERNAL_SYMBOL2 = MAX_EXTERNAL_OBJECT_NAME;
NamedPipeClient* namedPipe = nullptr;

// Constants
#define PUSH2_DISPLAY_WIDTH 960
#define PUSH2_DISPLAY_HEIGHT 160
#define PUSH2_DISPLAY_MESSAGE_BUFFER_SIZE 16384
#define PUSH2_DISPLAY_IMAGE_BUFFER_SIZE PUSH2_DISPLAY_WIDTH * PUSH2_DISPLAY_HEIGHT

// Struct definition
typedef struct _jit_matrix_handler
{
    t_object object;
    void* additional_inlet;
    t_bool status;
    t_object* live_frame;
    RGB* cached_live_rgb;
    CRITICAL_SECTION cache_lock;
    struct _jit_matrix_handler* next_instance;
} t_jit_matrix_handler;

// Prototypes
BEGIN_USING_C_LINKAGE
t_jit_err jit_matrix_handler_init();
t_jit_matrix_handler* jit_matrix_handler_new();
void jit_matrix_handler_free(t_jit_matrix_handler* x);
t_jit_err jit_matrix_input(t_jit_matrix_handler* x, void* inputs, void* outputs);
void jit_matrix_handler_blend(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv);
void jit_matrix_handler_getpixel(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv);
void jit_matrix_handler_getsignature(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv);
END_USING_C_LINKAGE

// Globals
static t_class* s_jit_matrix_handler_class = NULL;
static t_symbol* _sym_status;

const char* PIPE_NAME = "\\\\.\\pipe\\Push2Pipe";

// Process-wide service state
static t_jit_matrix_handler* s_instances_head = NULL;
static long s_instance_count = 0;
static bool s_connection_started_sent = false;
static bool s_editor_taken_over = false;
static bool s_frame_send_busy = false;
static bool s_frame_import_busy = false;
static bool s_blend_busy = false;
static bool s_services_started = false;
static bool s_services_starting = false;
static bool s_process_is_max_editor = false;
static bool s_process_host_known = false;
static CRITICAL_SECTION s_service_lock;
static bool s_service_lock_initialized = false;
static long s_debug_getframe_request_counter = 0;

// -------------------------------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------------------------------

extern "C" void proxy_service_lock()
{
    if (s_service_lock_initialized)
    {
        EnterCriticalSection(&s_service_lock);
    }
}

extern "C" void proxy_service_unlock()
{
    if (s_service_lock_initialized)
    {
        LeaveCriticalSection(&s_service_lock);
    }
}

static void notify_noargs(t_jit_matrix_handler* x, const char* message)
{
    if (!x || !message)
    {
        return;
    }

    object_notify(x, gensym((char*)message), NULL);
}

static void notify_error_reason(t_jit_matrix_handler* x, const char* reason)
{
    if (!x || !reason)
    {
        return;
    }

    t_atom av[1];
    atom_setsym(av, gensym((char*)reason));

    t_atomarray* aa = atomarray_new(1, av);
    object_notify(x, gensym("error"), aa);
    object_free(aa);
}

static void broadcast_noargs(const char* message)
{
    t_jit_matrix_handler* it = s_instances_head;
    while (it)
    {
        notify_noargs(it, message);
        it = it->next_instance;
    }
}

static void register_instance(t_jit_matrix_handler* x)
{
    if (!x)
    {
        return;
    }

    x->next_instance = s_instances_head;
    s_instances_head = x;
    s_instance_count++;
}

static void unregister_instance(t_jit_matrix_handler* x)
{
    if (!x)
    {
        return;
    }

    t_jit_matrix_handler* prev = NULL;
    t_jit_matrix_handler* it = s_instances_head;

    while (it)
    {
        if (it == x)
        {
            if (prev)
            {
                prev->next_instance = it->next_instance;
            }
            else
            {
                s_instances_head = it->next_instance;
            }

            x->next_instance = NULL;
            if (s_instance_count > 0)
            {
                s_instance_count--;
            }
            return;
        }

        prev = it;
        it = it->next_instance;
    }
}

extern "C" void proxy_notify_connection_started()
{
    proxy_service_lock();

    if (!s_connection_started_sent && s_instances_head)
    {
        s_connection_started_sent = true;
        post("proxy event: connection_started");
        DEBUG_LOG("proxy event: connection_started");
        broadcast_noargs("connection_started");
    }

    proxy_service_unlock();
}

extern "C" void proxy_notify_max_editor_started()
{
    proxy_service_lock();

    if (s_instances_head)
    {
        s_editor_taken_over = true;
        post("proxy event: max_editor_started");
        DEBUG_LOG("proxy event: max_editor_started");
        broadcast_noargs("max_editor_started");
    }

    proxy_service_unlock();
}

extern "C" void proxy_notify_max_editor_ended()
{
    proxy_service_lock();

    if (s_instances_head)
    {
        s_editor_taken_over = false;
        post("proxy event: max_editor_ended");
        DEBUG_LOG("proxy event: max_editor_ended");
        broadcast_noargs("max_editor_ended");
    }

    proxy_service_unlock();
}

extern "C" void proxy_notify_error_frame_not_sent()
{
    proxy_service_lock();

    t_jit_matrix_handler* it = s_instances_head;
    while (it)
    {
        notify_error_reason(it, "frame_not_sent");
        it = it->next_instance;
    }

    proxy_service_unlock();
}

extern "C" void proxy_notify_error_live_frame_not_available()
{
    proxy_service_lock();

    t_jit_matrix_handler* it = s_instances_head;
    while (it)
    {
        notify_error_reason(it, "live_frame_not_available");
        it = it->next_instance;
    }

    proxy_service_unlock();
}

extern "C" void proxy_notify_error_blend_not_set()
{
    proxy_service_lock();

    t_jit_matrix_handler* it = s_instances_head;
    while (it)
    {
        notify_error_reason(it, "blend_not_set");
        it = it->next_instance;
    }

    proxy_service_unlock();
}

static bool host_is_max_editor(const char* host_path)
{
    const char* file_name = strrchr(host_path, '\\');

    if (file_name)
    {
        file_name++;
    }
    else
    {
        file_name = host_path;
    }

    if (_stricmp(file_name, "Max.exe") == 0)
    {
        return true;
    }

    return false;
}

static void services_ensure_started(bool send_takeover)
{
    proxy_service_lock();

    if (s_services_started)
    {
        post("services_ensure_started: services already started");
        DEBUG_LOG("services_ensure_started: services already started");
        proxy_service_unlock();
        return;
    }

    if (s_services_starting)
    {
        post("services_ensure_started: start already in progress");
        DEBUG_LOG("services_ensure_started: start already in progress");
        proxy_service_unlock();
        return;
    }

    s_services_starting = true;
    proxy_service_unlock();

    post("services_ensure_started: send_takeover=%d", send_takeover ? 1 : 0);
    DEBUG_LOG("services_ensure_started: send_takeover=%d", send_takeover ? 1 : 0);

    takeover_init();

    if (send_takeover)
    {
        post("About to send takeover bang");
        DEBUG_LOG("About to send takeover bang");
        takeover_send_bang();
        post("Sleeping 30 ms after takeover bang");
        DEBUG_LOG("Sleeping 30 ms after takeover bang");
        Sleep(30);
    }
    else
    {
        post("Starting without automatic takeover");
        DEBUG_LOG("Starting without automatic takeover");
    }

    takeover_lock_pipe();
    namedPipe = new NamedPipeClient(PIPE_NAME);
    takeover_unlock_pipe();

    proxy_service_lock();

    if (!namedPipe)
    {
        post("services_ensure_started: failed to create NamedPipeClient");
        DEBUG_LOG("services_ensure_started: failed to create NamedPipeClient");
        s_services_starting = false;
        proxy_service_unlock();
        return;
    }

    post("NamedPipeClient created");
    DEBUG_LOG("NamedPipeClient created: %p", namedPipe);

    startHeartbeat(namedPipe, 500);
    post("Heartbeat started");
    DEBUG_LOG("Heartbeat started");

    if (!send_takeover)
    {
        takeover_start_listener();
        post("Takeover listener start requested");
        DEBUG_LOG("Takeover listener start requested");
    }
    else
    {
        post("Takeover listener skipped in Max editor process");
        DEBUG_LOG("Takeover listener skipped in Max editor process");
    }

    s_services_started = true;
    s_services_starting = false;
    proxy_service_unlock();
}

static void services_stop()
{
    proxy_service_lock();

    post("services_stop");
    DEBUG_LOG("services_stop");

    takeover_lock_pipe();

    stopHeartbeat();

    if (namedPipe)
    {
        delete namedPipe;
        namedPipe = nullptr;
    }

    takeover_unlock_pipe();

    takeover_stop_listener();
    takeover_free();

    if (s_process_host_known && s_process_is_max_editor)
    {
        post("services_stop: sending reactivate bang from Max editor process");
        DEBUG_LOG("services_stop: sending reactivate bang from Max editor process");
        takeover_send_reactivate_bang();
    }

    s_connection_started_sent = false;
    s_editor_taken_over = false;
    s_frame_send_busy = false;
    s_frame_import_busy = false;
    s_blend_busy = false;
    s_services_started = false;
    s_services_starting = false;
    s_process_is_max_editor = false;
    s_process_host_known = false;

    proxy_service_unlock();
}

// -------------------------------------------------------------------------------------------------
// Class registration
// -------------------------------------------------------------------------------------------------

t_jit_err jit_matrix_handler_init()
{
    post("In jit_matrix_handler_init");
    DEBUG_LOG("In jit_matrix_handler_init");

    if (!s_service_lock_initialized)
    {
        InitializeCriticalSection(&s_service_lock);
        s_service_lock_initialized = true;
    }

    t_jit_object* mop;

    _sym_status = gensym("status");

    s_jit_matrix_handler_class = (t_class*)jit_class_new(
        MAX_EXTERNAL_SYMBOL2,
        (method)jit_matrix_handler_new,
        (method)jit_matrix_handler_free,
        sizeof(t_jit_matrix_handler),
        0
    );

    mop = (t_jit_object*)jit_object_new(_jit_sym_jit_mop, 1, 1);
    jit_mop_single_type(mop, _jit_sym_char);
    jit_mop_single_planecount(mop, 4);

    t_atom args[2];
    jit_atom_setlong(args, PUSH2_DISPLAY_WIDTH);
    jit_atom_setlong(args + 1, PUSH2_DISPLAY_HEIGHT);

    void* input = jit_object_method(mop, _jit_sym_getinput, 1);
    jit_object_method(input, _jit_sym_mindim, 2, &args);
    jit_object_method(input, _jit_sym_maxdim, 2, &args);
    jit_object_method(input, _jit_sym_ioproc, jit_mop_ioproc_copy_adapt);

    jit_class_addadornment(s_jit_matrix_handler_class, mop);

    t_jit_object* attr = (t_jit_object*)jit_object_new(
        _jit_sym_jit_attr_offset,
        "status",
        _jit_sym_char,
        JIT_ATTR_GET_DEFER_LOW | JIT_ATTR_SET_USURP_LOW | JIT_ATTR_SET_OPAQUE_USER,
        (method)0L,
        (method)0L,
        calcoffset(t_jit_matrix_handler, status)
    );
    jit_class_addattr(s_jit_matrix_handler_class, attr);

    jit_class_addmethod(s_jit_matrix_handler_class, (method)jit_matrix_input, "matrix_calc", A_CANT, 0);
    jit_class_addmethod(s_jit_matrix_handler_class, (method)jit_matrix_handler_blend, "blend", A_GIMME, 0);
    jit_class_addmethod(s_jit_matrix_handler_class, (method)jit_matrix_handler_getpixel, "getpixel", A_GIMME, 0);
    jit_class_addmethod(s_jit_matrix_handler_class, (method)jit_matrix_handler_getsignature, "getsignature", A_GIMME, 0);
    jit_class_addmethod(s_jit_matrix_handler_class, (method)jit_object_register, "register", A_CANT, 0);

    jit_class_register(s_jit_matrix_handler_class);

    return JIT_ERR_NONE;
}

// -------------------------------------------------------------------------------------------------
// Object lifecycle
// -------------------------------------------------------------------------------------------------

t_jit_matrix_handler* jit_matrix_handler_new()
{
    post("In jit_matrix_handler_new");
    DEBUG_LOG("In jit_matrix_handler_new");

    char host_path[MAX_PATH] = { 0 };
    GetModuleFileNameA(NULL, host_path, MAX_PATH);
    post("jit_matrix_handler_new host: %s", host_path);
    DEBUG_LOG("jit_matrix_handler_new host: %s", host_path);

    bool send_takeover = host_is_max_editor(host_path);

    proxy_service_lock();

    if (!s_process_host_known)
    {
        s_process_is_max_editor = send_takeover;
        s_process_host_known = true;
    }

    t_jit_matrix_handler* x = (t_jit_matrix_handler*)jit_object_alloc(s_jit_matrix_handler_class);
    if (x)
    {
        x->status = FALSE;
        x->additional_inlet = inlet_new((t_object*)x, NULL);
        x->next_instance = NULL;
    }

    long dims[2] = { PUSH2_DISPLAY_WIDTH, PUSH2_DISPLAY_HEIGHT };
    t_jit_matrix_info info;
    memset(&info, 0, sizeof(info));
    info.type = _jit_sym_char;
    info.planecount = 4;
    info.dimcount = 2;
    info.dim[0] = dims[0];
    info.dim[1] = dims[1];

    x->live_frame = (t_object*)jit_object_new(_jit_sym_jit_matrix);
    jit_object_method(x->live_frame, _jit_sym_setinfo, &info);
    jit_object_method(x->live_frame, _jit_sym_clear);

    x->cached_live_rgb = (RGB*)sysmem_newptrclear(
        PUSH2_DISPLAY_WIDTH * PUSH2_DISPLAY_HEIGHT * sizeof(RGB)
    );

    InitializeCriticalSection(&x->cache_lock);

    register_instance(x);

    proxy_service_unlock();

    services_ensure_started(send_takeover);

    proxy_service_lock();

    if (s_connection_started_sent)
    {
        notify_noargs(x, "connection_started");
    }

    if (s_editor_taken_over)
    {
        notify_noargs(x, "max_editor_started");
    }

    proxy_service_unlock();

    return x;
}

void jit_matrix_handler_free(t_jit_matrix_handler* x)
{
    post("In jit_matrix_handler_free");
    DEBUG_LOG("In jit_matrix_handler_free");

    proxy_service_lock();

    unregister_instance(x);

    bool stop_services = (s_instance_count == 0);

    proxy_service_unlock();

    if (stop_services)
    {
        services_stop();
    }

    if (x->live_frame)
    {
        object_free(x->live_frame);
        x->live_frame = NULL;
    }

    if (x->cached_live_rgb)
    {
        sysmem_freeptr(x->cached_live_rgb);
        x->cached_live_rgb = NULL;
    }

    DeleteCriticalSection(&x->cache_lock);
}

// -------------------------------------------------------------------------------------------------
// Pipe send helper
// -------------------------------------------------------------------------------------------------

static int sendMatrixRowViaPipe(const void* matrixData, int width, int line, int planecount)
{
    pipe_data_transfer pd;
    memset(&pd, 0, sizeof(pd));

    sprintf(pd.type, "DATA");
    sprintf(pd.message, "MaxDataLine");
    pd.lineNr = (BYTE)line;

    if (planecount == 4)
    {
        unsigned char* rgbSourcePtr = (unsigned char*)matrixData + 1;
        DWORD* pixelSourcePtr = (DWORD*)rgbSourcePtr + line * width;
        RGB* pixelDestPtr = (RGB*)pd.pixels;

        for (int pixel = 0; pixel < width; pixel++)
        {
            *(DWORD*)(pixelDestPtr + pixel) = pixelSourcePtr[pixel];
        }
    }
    else if (planecount == 3)
    {
        memcpy(pd.pixels, (const unsigned char*)matrixData + line * width * sizeof(RGB), width * sizeof(RGB));
    }

    takeover_lock_pipe();

    if (!namedPipe)
    {
        takeover_unlock_pipe();
        return 0;
    }

    DWORD replySize = namedPipe->sendMessageNoReply((const char*)&pd, sizeof(pd));

    takeover_unlock_pipe();

    return (int)replySize;
}

extern "C" t_jit_err jit_matrix_input(t_jit_matrix_handler* x, void* inputs, void* outputs)
{
    LARGE_INTEGER freq, start, end;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    if (!x)
    {
        return JIT_ERR_INVALID_PTR;
    }

    void* input_matrix = jit_object_method(inputs, _jit_sym_getindex, 0);
    if (!input_matrix)
    {
        return JIT_ERR_INVALID_PTR;
    }

    t_jit_err input_lock = (t_jit_err)(intptr_t)jit_object_method(input_matrix, _jit_sym_lock, 1);

    t_jit_matrix_info input_info;
    memset(&input_info, 0, sizeof(input_info));
    jit_object_method(input_matrix, _jit_sym_getinfo, &input_info);

    proxy_service_lock();

    if (takeover_is_taken_over())
    {
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        return JIT_ERR_SUPPRESS_OUTPUT;
    }

    // Get live frame branch
    if (input_info.dimcount == 2 && input_info.planecount == 1 && input_info.dim[0] == 1)
    {
        long request_id = ++s_debug_getframe_request_counter;
        post("GetFrame request begin: id=%ld x=%p instances=%ld", request_id, x, s_instance_count);
        DEBUG_LOG("GetFrame request begin: id=%ld x=%p instances=%ld", request_id, x, s_instance_count);

        if (s_frame_import_busy || s_frame_send_busy || s_blend_busy)
        {
            post("GetFrame request blocked busy: id=%ld x=%p send=%d import=%d blend=%d", request_id, x, s_frame_send_busy ? 1 : 0, s_frame_import_busy ? 1 : 0, s_blend_busy ? 1 : 0);
            DEBUG_LOG("GetFrame request blocked busy: id=%ld x=%p send=%d import=%d blend=%d", request_id, x, s_frame_send_busy ? 1 : 0, s_frame_import_busy ? 1 : 0, s_blend_busy ? 1 : 0);
            proxy_service_unlock();
            jit_object_method(input_matrix, _jit_sym_lock, input_lock);
            notify_error_reason(x, "live_frame_not_available");
            return JIT_ERR_GENERIC;
        }

        s_frame_import_busy = true;

        t_jit_err live_lock = (t_jit_err)(intptr_t)jit_object_method(x->live_frame, _jit_sym_lock, 1);

        pipe_get_frame_command gfr;
        memset(&gfr, 0, sizeof(gfr));
        strcpy(gfr.type, "COMMAND");
        strcpy(gfr.message, "GetFrame");

        pipe_frame_transfer replyBuffer;
        memset(&replyBuffer, 0, sizeof(replyBuffer));

        DWORD result = 0;

        takeover_lock_pipe();
        if (namedPipe)
        {
            result = namedPipe->sendMessageWithReply((const char*)&gfr, sizeof(gfr), &replyBuffer, sizeof(pipe_frame_transfer));
        }
        takeover_unlock_pipe();

        if (!result)
        {
            post("GetFrame request failed: id=%ld x=%p", request_id, x);
            DEBUG_LOG("GetFrame request failed: id=%ld x=%p", request_id, x);
            s_frame_import_busy = false;
            proxy_service_unlock();
            jit_object_method(x->live_frame, _jit_sym_lock, live_lock);
            jit_object_method(input_matrix, _jit_sym_lock, input_lock);
            notify_error_reason(x, "live_frame_not_available");
            return JIT_ERR_GENERIC;
        }

        char* live_frame_data;
        jit_object_method(x->live_frame, _jit_sym_getdata, &live_frame_data);
        if (!live_frame_data)
        {
            post("GetFrame request no data ptr: id=%ld x=%p", request_id, x);
            DEBUG_LOG("GetFrame request no data ptr: id=%ld x=%p", request_id, x);
            s_frame_import_busy = false;
            proxy_service_unlock();
            jit_object_method(x->live_frame, _jit_sym_lock, live_lock);
            jit_object_method(input_matrix, _jit_sym_lock, input_lock);
            notify_error_reason(x, "live_frame_not_available");
            return JIT_ERR_INVALID_PTR;
        }

        EnterCriticalSection(&x->cache_lock);

        RGB* sourcePixels = replyBuffer.pixels;
        RGB* cachePixels = x->cached_live_rgb;
        char* dest = live_frame_data;

        for (int y = 0; y < PUSH2_DISPLAY_HEIGHT; y++)
        {
            for (int xp = 0; xp < PUSH2_DISPLAY_WIDTH; xp++)
            {
                RGB pixel = sourcePixels[y * PUSH2_DISPLAY_WIDTH + xp];
                cachePixels[y * PUSH2_DISPLAY_WIDTH + xp] = pixel;

                *dest++ = 255;
                *dest++ = pixel.r;
                *dest++ = pixel.g;
                *dest++ = pixel.b;
            }
        }

        LeaveCriticalSection(&x->cache_lock);
        s_frame_import_busy = false;
        proxy_service_unlock();

        void* output_matrix = jit_object_method(outputs, _jit_sym_getindex, 0);
        if (!output_matrix)
        {
            jit_object_method(x->live_frame, _jit_sym_lock, live_lock);
            jit_object_method(input_matrix, _jit_sym_lock, input_lock);
            return JIT_ERR_INVALID_PTR;
        }

        t_jit_matrix_info output_info;
        memset(&output_info, 0, sizeof(output_info));
        jit_object_method(x->live_frame, _jit_sym_getinfo, &output_info);

        jit_object_method(output_matrix, _jit_sym_setinfo, &output_info);
        jit_object_method(output_matrix, _jit_sym_clear);
        jit_object_method(output_matrix, _jit_sym_frommatrix, x->live_frame);

        jit_object_method(x->live_frame, _jit_sym_lock, live_lock);
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);

        post("GetFrame request notify live_frame_ready: id=%ld x=%p", request_id, x);
        DEBUG_LOG("GetFrame request notify live_frame_ready: id=%ld x=%p", request_id, x);
        notify_noargs(x, "live_frame_ready");

        return JIT_ERR_NONE;
    }

    if (input_info.dimcount != 2)
    {
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        return JIT_ERR_INVALID_INPUT;
    }

    if (input_info.planecount != 3 && input_info.planecount != 4)
    {
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        return JIT_ERR_INVALID_INPUT;
    }

    if (input_info.dim[0] != PUSH2_DISPLAY_WIDTH || input_info.dim[1] != PUSH2_DISPLAY_HEIGHT)
    {
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        return JIT_ERR_INVALID_INPUT;
    }

    if (s_frame_send_busy || s_frame_import_busy || s_blend_busy)
    {
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        notify_error_reason(x, "frame_not_sent");
        return JIT_ERR_GENERIC;
    }

    s_frame_send_busy = true;

    char* input_data;
    jit_object_method(input_matrix, _jit_sym_getdata, &input_data);
    if (!input_data)
    {
        s_frame_send_busy = false;
        proxy_service_unlock();
        jit_object_method(input_matrix, _jit_sym_lock, input_lock);
        return JIT_ERR_INVALID_INPUT;
    }

    for (int line = 0; line < PUSH2_DISPLAY_HEIGHT; line++)
    {
        int replySize = sendMatrixRowViaPipe(input_data, PUSH2_DISPLAY_WIDTH, line, input_info.planecount);
        if (replySize == 0)
        {
            s_frame_send_busy = false;
            proxy_service_unlock();
            jit_object_method(input_matrix, _jit_sym_lock, input_lock);
            notify_error_reason(x, "frame_not_sent");
            return JIT_ERR_GENERIC;
        }
    }

    s_frame_send_busy = false;
    proxy_service_unlock();
    jit_object_method(input_matrix, _jit_sym_lock, input_lock);

    QueryPerformanceCounter(&end);
    double elapsedMs = static_cast<double>(end.QuadPart - start.QuadPart) * 1000.0 / freq.QuadPart;
    post("jit_matrix_input: Frame sent via pipe in %f ms", elapsedMs);
    DEBUG_LOG("jit_matrix_input: Frame sent via pipe in %f ms", elapsedMs);

    notify_noargs(x, "frame_sent_ready");

    return JIT_ERR_SUPPRESS_OUTPUT;
}

// -------------------------------------------------------------------------------------------------
// Commands
// -------------------------------------------------------------------------------------------------

void jit_matrix_handler_blend(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv)
{
    proxy_service_lock();

    if (takeover_is_taken_over())
    {
        proxy_service_unlock();
        return;
    }

    if (s_blend_busy || s_frame_send_busy || s_frame_import_busy)
    {
        proxy_service_unlock();
        notify_error_reason(x, "blend_not_set");
        return;
    }

    int xPos = 0;
    int yPos = 0;
    int width = PUSH2_DISPLAY_WIDTH;
    int height = PUSH2_DISPLAY_HEIGHT;
    float maxBlendF = -1.0f;
    float liveBlendF = -1.0f;

    if (argc < 1)
    {
        proxy_service_unlock();
        notify_error_reason(x, "blend_not_set");
        return;
    }

    if (argc == 6)
    {
        xPos = atom_getlong(argv);
        yPos = atom_getlong(argv + 1);
        width = atom_getlong(argv + 2);
        height = atom_getlong(argv + 3);
        maxBlendF = atom_getfloat(argv + 4);
        liveBlendF = atom_getfloat(argv + 5);
    }
    else if (argc == 5)
    {
        xPos = atom_getlong(argv);
        yPos = atom_getlong(argv + 1);
        width = atom_getlong(argv + 2);
        height = atom_getlong(argv + 3);
        maxBlendF = atom_getfloat(argv + 4);
        liveBlendF = 0.0f;
    }
    else if (argc == 2)
    {
        maxBlendF = atom_getfloat(argv);
        liveBlendF = atom_getfloat(argv + 1);
    }
    else if (argc == 1)
    {
        if (atom_gettype(argv) == A_SYM)
        {
            t_symbol* sym = atom_getsym(argv);
            if (strcmp(sym->s_name, "max") == 0)
            {
                maxBlendF = 1.0f;
                liveBlendF = 0.0f;
            }
            else if (strcmp(sym->s_name, "live") == 0)
            {
                maxBlendF = 0.0f;
                liveBlendF = 1.0f;
            }
            else
            {
                proxy_service_unlock();
                notify_error_reason(x, "blend_not_set");
                return;
            }
        }
        else
        {
            float numericVal = atom_getfloat(argv);
            if (numericVal == 0.0f)
            {
                maxBlendF = 0.0f;
                liveBlendF = 1.0f;
            }
            else
            {
                maxBlendF = numericVal;
                liveBlendF = 0.0f;
            }
        }
    }
    else
    {
        proxy_service_unlock();
        notify_error_reason(x, "blend_not_set");
        return;
    }

    if (maxBlendF < 0.0f)
    {
        maxBlendF = 0.0f;
    }
    if (maxBlendF > 1.275f)
    {
        maxBlendF = 1.275f;
    }
    if (liveBlendF < 0.0f)
    {
        liveBlendF = 0.0f;
    }
    if (liveBlendF > 1.275f)
    {
        liveBlendF = 1.275f;
    }

    unsigned char maxBlend = (unsigned char)(maxBlendF * 200.0f + 0.5f);
    unsigned char liveBlend = (unsigned char)(liveBlendF * 200.0f + 0.5f);

    pipe_blend_command pdc;
    memset(&pdc, 0, sizeof(pdc));
    strcpy(pdc.type, "COMMAND");
    strcpy(pdc.message, "Blend");
    pdc.xPos = xPos;
    pdc.yPos = yPos;
    pdc.width = width;
    pdc.height = height;
    pdc.maxBlend = maxBlend;
    pdc.liveBlend = liveBlend;

    s_blend_busy = true;

    takeover_lock_pipe();

    if (!namedPipe)
    {
        takeover_unlock_pipe();
        s_blend_busy = false;
        proxy_service_unlock();
        notify_error_reason(x, "blend_not_set");
        return;
    }

    DWORD result = namedPipe->sendMessageNoReply((const char*)&pdc, sizeof(pdc));

    takeover_unlock_pipe();
    s_blend_busy = false;
    proxy_service_unlock();

    if (result == 0)
    {
        notify_error_reason(x, "blend_not_set");
        return;
    }

    notify_noargs(x, "blend_ready");
}

void jit_matrix_handler_getpixel(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv)
{
    if (argc != 2)
    {
        return;
    }

    int xPos = atom_getlong(argv);
    int yPos = atom_getlong(argv + 1);
    if (xPos < 0 || xPos > 959 || yPos < 0 || yPos > 159)
    {
        return;
    }

    EnterCriticalSection(&x->cache_lock);
    RGB px = x->cached_live_rgb[yPos * 960 + xPos];
    LeaveCriticalSection(&x->cache_lock);

    t_atom av[6];
    atom_setlong(av + 0, px.r);
    atom_setlong(av + 1, px.g);
    atom_setlong(av + 2, px.b);
    atom_setlong(av + 3, px.r + px.g + px.b);
    atom_setlong(av + 4, xPos);
    atom_setlong(av + 5, yPos);

    t_atomarray* aa = atomarray_new(6, av);
    object_notify(x, gensym("pixel"), aa);
    object_free(aa);
}

void jit_matrix_handler_getsignature(t_jit_matrix_handler* x, t_symbol* s, long argc, t_atom* argv)
{
    if (argc < 5)
    {
        return;
    }

    int xPos = atom_getlong(argv + 0);
    int yPos = atom_getlong(argv + 1);
    int width = atom_getlong(argv + 2);
    int height = atom_getlong(argv + 3);

    if (xPos < 0 || xPos > 959 || yPos < 0 || yPos > 159 || width < 1 || height < 1 || xPos + width > 960 || yPos + height > 160)
    {
        return;
    }

    int minR = 0;
    int maxR = 255;
    int minG = 0;
    int maxG = 255;
    int minB = 0;
    int maxB = 255;
    int minSum = 0;
    int maxSum = 255 * 3;

    int i = 4;

    while (i < argc)
    {
        if (atom_gettype(argv + i) != A_SYM)
        {
            return;
        }

        t_symbol* mode = atom_getsym(argv + i);
        bool sum = false;
        if (strcmp(mode->s_name, "sum") == 0)
        {
            sum = true;
        }
        else if (strcmp(mode->s_name, "rgb") == 0)
        {
            sum = false;
        }
        else
        {
            return;
        }

        if (i + 2 >= argc || atom_gettype(argv + i + 1) != A_SYM)
        {
            return;
        }

        t_symbol* cond = atom_getsym(argv + i + 1);
        long arg1 = 0;
        long arg2 = 0;
        long arg3 = 0;

        if (i + 2 < argc)
        {
            arg1 = atom_getlong(argv + i + 2);
        }
        if (i + 3 < argc && atom_gettype(argv + i + 3) != A_SYM)
        {
            arg2 = atom_getlong(argv + i + 3);
        }
        if (i + 4 < argc && atom_gettype(argv + i + 4) != A_SYM)
        {
            arg3 = atom_getlong(argv + i + 4);
        }

        int consumed = 0;
        if (sum)
        {
            consumed = 3;
        }
        else
        {
            consumed = 5;
        }

        i += consumed;

        if (strcmp(cond->s_name, "=") == 0 && sum == true)
        {
            minSum = maxSum = arg1 * 3;
        }
        else if (strcmp(cond->s_name, "=") == 0 && sum == false)
        {
            if (i > argc + 1)
            {
                return;
            }
            minR = maxR = arg1;
            minG = maxG = arg2;
            minB = maxB = arg3;
        }
        else if (strcmp(cond->s_name, ">=") == 0 && sum == true)
        {
            minSum = arg1 * 3;
        }
        else if (strcmp(cond->s_name, ">=") == 0 && sum == false)
        {
            minR = arg1;
            minG = arg2;
            minB = arg3;
        }
        else if (strcmp(cond->s_name, "<=") == 0 && sum == true)
        {
            maxSum = arg1 * 3;
        }
        else if (strcmp(cond->s_name, "<=") == 0 && sum == false)
        {
            maxR = arg1;
            maxG = arg2;
            maxB = arg3;
        }
        else
        {
            return;
        }
    }

    EnterCriticalSection(&x->cache_lock);

    int count = 0;
    int total = 0;
    uint16_t signature = 0;

    for (int yp = yPos; yp < yPos + height; yp++)
    {
        for (int xp = xPos; xp < xPos + width; xp++)
        {
            signature += signature + (signature >> 15);
            total++;
            RGB px = x->cached_live_rgb[yp * 960 + xp];
            if (px.r + px.g + px.b <= maxSum
                && px.r + px.g + px.b >= minSum
                && px.r <= maxR
                && px.r >= minR
                && px.g <= maxG
                && px.g >= minG
                && px.b <= maxB
                && px.b >= minB)
            {
                count++;
                signature += (xp << 8) + yp;
            }
        }
    }

    LeaveCriticalSection(&x->cache_lock);

    t_atom av[8];
    atom_setlong(av + 0, signature);
    atom_setlong(av + 1, count);
    atom_setlong(av + 2, total);
    atom_setsym(av + 3, gensym("region"));
    atom_setlong(av + 4, xPos);
    atom_setlong(av + 5, yPos);
    atom_setlong(av + 6, width);
    atom_setlong(av + 7, height);

    t_atomarray* aa = atomarray_new(8, av);
    object_notify(x, gensym("signature"), aa);
    object_free(aa);
}
