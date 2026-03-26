#pragma once

#include "RGB.h"

typedef struct pipe_message_transfer {
	char type[10];           // e.g., "MESS"
	char message[64];        // zero-delimited string; for reply, e.g., "Ok" or "Error"
};

// Message type to send a line of Push2 LCD pixels
typedef struct pipe_data_transfer {
	char type[10];           // should be "DATA"
	char message[64];        // zero-delimited string, e.g., "MaxData line 12"
	BYTE lineNr;             // the line number (0 to 159)
	RGB pixels[960];         // one row of 960 pixels (each pixel is an RGB)
	unsigned char filler;    // We will copy one byte extra when filling the RGB pixel buffer
};

typedef struct pipe_frame_transfer {
	char type[10];          // should be "DATA"
	char message[8];        // should be "Frame"
	RGB pixels[960 * 160];  // 160 rows of 960 pixels (each pixel is an RGB)
	unsigned char filler;   // We will copy one byte extra when filling the RGB pixel buffer
	//LONG checksum;        // a simple checksum (for example, the sum of all bytes)
};

struct pipe_blend_command {
	char type[10];           // should be COMMAND
	char message[8];         // shoud be Blend
	int xPos;
	int yPos;
	int width;
	int height;
	unsigned char maxBlend;  // unsigned char 0 - 255, 200 is default, or 0.0 to 1.275
	unsigned char liveBlend; // unsigned char 0 - 255, 200 is default, or 0.0 to 1.275
};

// Prepare a blend command message to send via the named pipe.
struct pipe_heartbeat_command {
	char type[10];          // Should be COMMAND
	char message[10];        // Should be Heartbeat
};

// Get a line from the current Live frame for Push2
struct pipe_get_live_frame_line_command {
	char type[10];           // Should be COMMAND
	char message[10];        // Should be GetLine
	int line;
};

// Get the current Live frame for Push2
struct pipe_get_frame_command {
	char type[10];           // Should be COMMAND
	char message[10];        // Should be GetFrame
};

