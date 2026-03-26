#include <cstddef>   // For size_t
#include "Debug.h"
#include "jit_wjl_push2_lcd.h"
#include <windows.h>

// From the C74 SDK version 6
#include "jit.common.h"
#include "max.jit.mop.h"

extern "C" IMAGE_DOS_HEADER __ImageBase;

const char* MAX_EXTERNAL_SYMBOL = MAX_EXTERNAL_OBJECT_NAME;

// Struct definition
typedef struct _max_external {
    t_object object;
    void* obex;
    t_symbol* server_name;
} t_max_external;

// Prototypes
BEGIN_USING_C_LINKAGE
t_jit_err jit_matrix_handler_init(void);
void* jit_external_new(t_symbol* s, long argc, t_atom* argv);
void jit_matrix_handler_free_memory(t_max_external* x);
void max_jit_object_notify(t_max_external* x, t_symbol* s, t_symbol* msg, void* ob, void* data);
END_USING_C_LINKAGE

// Global class pointer
static void* s_max_external_class = NULL;
static t_symbol* ps_live_frame_ready;  // symbool-cache

extern void heartbeat_start();
extern void heartbeat_stop();

// Class registration
// Note: __declspec(dllexport) makes ext_main visible externally.
extern "C" __declspec(dllexport) 
void ext_main(void* r)
{
    post("In ext_main of 'jit.wjl_push2_lcd', build %s %s", __DATE__, __TIME__);
    DEBUG_LOG("In ext_main of 'jit.wjl_push2_lcd', build %s %s", __DATE__, __TIME__);

    char path[MAX_PATH];
    GetModuleFileNameA((HMODULE)&__ImageBase, path, MAX_PATH);
    post("jit.wjl_push2_lcd is loaded from: %s", path);

    common_symbols_init();
    ps_live_frame_ready = gensym("live_frame_ready");

    t_class* max_class, *jit_class;

    // Initialize our underlying wjl.push object/class
    jit_matrix_handler_init();

    // Create our Max object class
    max_class = class_new(MAX_EXTERNAL_SYMBOL,
        (method)jit_external_new,
        (method)jit_matrix_handler_free_memory,  // <-- jouw free
        sizeof(t_max_external), NULL, A_GIMME, 0);
    max_jit_class_obex_setup(max_class, calcoffset(t_max_external, obex));

    // Find the Jitter class for wjl_push that was registered in our underlying code
    jit_class = (t_class*)jit_class_findbyname(gensym(MAX_EXTERNAL_SYMBOL));
    max_jit_class_mop_wrap(max_class, jit_class,
        MAX_JIT_MOP_FLAGS_OWN_ADAPT | MAX_JIT_MOP_FLAGS_OWN_OUTPUTMODE | MAX_JIT_MOP_FLAGS_OWN_NOTIFY);
    max_jit_class_wrap_standard(max_class, jit_class, 0);

    // Add standard methods
    class_addmethod(max_class, (method)max_jit_mop_assist, "assist", A_CANT, 0);
    class_addmethod(max_class, (method)max_jit_object_notify, "notify", A_CANT, 0);
    class_addmethod(max_class, (method)max_jit_mop_jit_matrix, "jit_matrix", A_GIMME, 0);
    class_addmethod(max_class, (method)max_jit_mop_bang, "bang", 0);

    // Register the class with Max
    class_register(CLASS_BOX, max_class);

    s_max_external_class = max_class;
}

// Object instantiation
void* jit_external_new(t_symbol* s, long argc, t_atom* argv)
{
    //post("In jit_external_new");
    DEBUG_LOG("In jit_external_new");
    t_max_external* x;
    void* o;

    x = (t_max_external*)max_jit_object_alloc((t_class*)s_max_external_class, gensym(MAX_EXTERNAL_SYMBOL));
    if (x) {
        o = jit_object_new(gensym(MAX_EXTERNAL_SYMBOL));
        if (o) {
            max_jit_mop_setup_simple(x, o, argc, argv);
            max_jit_attr_args(x, argc, argv);
            x->server_name = jit_symbol_unique();
            jit_object_method(o, _jit_sym_register, x->server_name);
            jit_object_attach(x->server_name, x);
        }
        else {
            jit_object_error((t_object*)x, "wjl.push: could not allocate object");
            object_free((t_object*)x);
            x = NULL;
        }
    }

    return x;
}

void jit_matrix_handler_free_memory(t_max_external* x)
{
    //post("FREE: jit_matrix_handler_free_memory");
    DEBUG_LOG("FREE: jit_matrix_handler_free_memory");

    if (x && x->server_name) {
        t_object* job = (t_object*)max_jit_obex_jitob_get(x);
        if (job) {
            jit_object_detach(x->server_name, x);
        }
    }

    max_jit_mop_free(x);
    jit_object_free(max_jit_obex_jitob_get(x));
    max_jit_obex_free(x);
}

void wjl_deferred_live_ready(t_max_external* x)
{
    // dumpout: live_frame_ready (zonder args)
    max_jit_obex_dumpout(x, ps_live_frame_ready, 0, NULL);
}

// Notification method
void max_jit_object_notify(t_max_external* x, t_symbol* s, t_symbol* msg, void* ob, void* data)
{
    if (msg == _sym_attr_modified) {
        t_jit_attr* attribute = (t_jit_attr *) data;
        t_jit_object* jitobj = (t_jit_object * ) max_jit_obex_jitob_get(x);
        t_atom_long status = jit_attr_getlong(jitobj, attribute->name);

        t_atom av[1];
        atom_setlong(av, status);
        max_jit_obex_dumpout(x, attribute->name, 1, av);
        //post("DUMPOUT", x, attribute->name, 1, av);
    }
    else if (msg == ps_live_frame_ready) {
        // Take care that dumpout comes after the frame is sent
        defer_low(x, (method)wjl_deferred_live_ready, NULL, 0, NULL);
    }
    else if (msg == gensym("pixel") || msg == gensym("signature")) {
        // data is a t_atomarray* you created on the Jitter side
        t_atomarray* aa = (t_atomarray*)data;
        long ac = 0;
        t_atom* av = NULL;
        if (aa) {
            atomarray_getatoms(aa, &ac, &av);
        }
        // forward to dumpout with the same selector
        max_jit_obex_dumpout(x, msg, ac, av);
        //return;
    }
    else {
        max_jit_mop_notify(x, s, msg);
    }
}
