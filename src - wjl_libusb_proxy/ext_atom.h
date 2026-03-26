#pragma once

#ifdef __cplusplus
extern "C" {
#endif

    // Define possible atom types.
    typedef enum _atomtype {
        A_NOTHING,
        A_LONG,
        A_FLOAT,
        A_SYM,
        A_OBJ,
        A_POINTER
    } t_atomtype;

    // A minimal definition for t_atom.
    typedef union _atom {
        long a_w;       // used for A_LONG
        float a_f;      // used for A_FLOAT
        char* a_s;      // used for A_SYM
        void* a_o;      // used for A_OBJ or A_POINTER
    } t_atom;

    // Macros to set values.
#define atom_setlong(a,v) ((a)->a_w = (v))
#define atom_setfloat(a,v) ((a)->a_f = (v))
#define atom_setsym(a,v) ((a)->a_s = (v))
#define atom_setobj(a,v) ((a)->a_o = (v))

// Macros to get values.
#define atom_getlong(a) ((a)->a_w)
#define atom_getfloat(a) ((a)->a_f)
#define atom_getsym(a) ((a)->a_s)
#define atom_getobj(a) ((a)->a_o)

#ifdef __cplusplus
}
#endif

