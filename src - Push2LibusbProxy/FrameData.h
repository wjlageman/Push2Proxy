#ifndef FRAMEDATA_H
#define FRAMEDATA_H

/*
#include "Push2Matrix.h"
#include "RGB.h"
#include "BlendPixel.h"

// Fixed dimensions for the Push2 LCD.
constexpr int MATRIX_WIDTH = 960;
constexpr int MATRIX_HEIGHT = 160;

// LocalData encapsulates our three matrices.
class LocalData {
public:
    // Pointers so that the matrices are allocated on the heap.
    Push2Matrix<RGB>* livePixels;
    Push2Matrix<RGB>* maxPixels;
    Push2Matrix<BlendPixel>* blendPixels;

    LocalData() {
        // Create the matrices.
        livePixels = new Push2Matrix<RGB>();
        maxPixels = new Push2Matrix<RGB>();
        blendPixels = new Push2Matrix<BlendPixel>();

        // Initialize blendPixels.
        // For instance, setting live to 255 (i.e. use the brightness from Live)
        // and max to 255 by default. You can change these defaults (e.g., 200)
        // if you want the possibility to boost brightness beyond the input.
        BlendPixel defaultBlend = { 200, 0 };
        blendPixels->fill(defaultBlend);
    }

    ~LocalData() {
        delete livePixels;
        delete maxPixels;
        delete blendPixels;
    }
};
*/
#endif // FRAMEDATA_H
