# Proxy Commands (wjl_libusb_proxy)

This document describes the command interface of the wjl_libusb_proxy Max external.

It is intended for developers who want to build custom control systems on top of Push2Proxy.

The external acts as a bridge between Max (Jitter) and the Push2 display via a named pipe.

---

## Overview

The external:

- Accepts Jitter matrices as input (display output)
- Sends frames to Push2
- Retrieves frames from Live
- Provides pixel and region analysis
- Controls blending between Max and Live

Transport layer:

Windows Named Pipe:
\\.\pipe\Push2Pipe

---

## Display Model

Push2 display:

- Width: 960 pixels
- Height: 160 pixels
- Format: RGB (3 planes) or RGBA (4 planes)

All operations are matrix-based.

---

## Why Frames Are Handled as Matrices

Frames are handled as Jitter matrices because:

- Jitter matrices are the native image format in Max
- No conversion is required between processing and display
- Pixel data is directly accessible
- Real-time processing is possible
- Regions can be updated independently

Internally, frames are transferred line-by-line over the pipe, but exposed to Max as a full matrix.

---

## Matrix Input (Display Output)

Input:

- Matrix dimensions must be 960 x 160
- Planecount must be 3 (RGB) or 4 (RGBA)

Behavior:

- Frame is sent line-by-line to the proxy
- Each line is transmitted via the pipe

On success:
frame_sent_ready

Errors:
frame_not_sent

Occurs when:

- Wrong matrix format
- System is busy
- Pipe is not available

---

## Special Input: GetFrame

A special case is used to request a frame from Live.

Trigger condition:

- dimcount = 2
- planecount = 1
- width = 1

Behavior:

- Sends GetFrame command to proxy
- Receives full frame from Live
- Converts to RGBA matrix
- Outputs matrix to Max

On success:
live_frame_ready

Errors:
live_frame_not_available

---

## Command: blend

Controls blending between Max and Live display content.

Supported forms:

Full control:
blend x y width height maxBlend liveBlend

Region + max blend:
blend x y width height maxBlend

Global blend:
blend maxBlend liveBlend

Symbolic:
blend max
blend live

Numeric shorthand:
blend 0   (full Live)
blend 1   (full Max)

Parameters:

x, y           → region position  
width, height  → region size  
maxBlend       → Max contribution (0.0 – ~1.275)  
liveBlend      → Live contribution (0.0 – ~1.275)  

Internally scaled to byte range.

On success:
blend_ready

Errors:
blend_not_set

Occurs when:

- Invalid arguments
- Busy state
- Pipe unavailable

---

## Command: getpixel

Reads a single pixel from the cached Live frame.

Syntax:

getpixel x y

Output:

pixel r g b sum x y

Where:

r, g, b → color values  
sum     → r + g + b  
x, y    → position  

Notes:

- Uses cached frame from last GetFrame
- Does not query Live directly

---

## Command: getsignature

Analyzes a region of the cached Live frame.

Syntax:

getsignature x y width height [filters...]

Filters:

RGB mode:

rgb >= r g b  
rgb <= r g b  
rgb = r g b  

Sum mode:

sum >= value  
sum <= value  
sum = value  

Output:

signature signatureValue count total region x y width height

Where:

signatureValue → computed identifier  
count          → matching pixels  
total          → total pixels in region  

---

## Notifications

Events:

connection_started  
max_editor_started  
max_editor_ended  
frame_sent_ready  
live_frame_ready  
blend_ready  

Errors:

frame_not_sent  
live_frame_not_available  
blend_not_set  

---

## Internal Constraints

Operations are mutually exclusive:

- frame send
- frame import
- blend

If one is active, others will fail.

---

## Takeover Behavior

When takeover is active:

- Matrix input is suppressed
- Display control is handled elsewhere

---

## Performance Notes

- Frames are transmitted line-by-line
- No compression is used
- Performance depends on pipe throughput

---

## Summary

The external provides:

- Matrix-based display output
- Frame retrieval from Live
- Pixel-level inspection
- Region analysis
- Display blending

It acts as an active bridge between Max and the Push2 display system.
