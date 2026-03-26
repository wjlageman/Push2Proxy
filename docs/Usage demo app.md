# Usage

This document describes how to use the demo application and explains the master track control setup.

---

## Demo Application

The demo files are located in:


/src - Max and Live


The main file is:


Push2Proxy_Max9.amxd


---

## Overview

The demo application shows the capabilities of Push2Proxy across multiple screens.

The main device contains:

- A single button to open the demo interface
- A tabstrip with multiple views
- A "View Patch" button to inspect the internal structure

---

## Navigation

- Use the tabstrip at the top to switch between views
- Each tab represents a different subsystem
- The "View Patch" button opens the current tab in edit mode

When you close a subpatch:

- The patching view remains visible
- Switching to another tab and back restores the presentation view

---

## Demo Sections

The demo includes the following components:

### LED Demo  
Shows the colors and behavior of LEDs, buttons, and encoders.

### Parameters  
Displays current parameter values, including minimum and maximum.

### Liveset with Red Ring  
Displays the Live set on the Push2 screen, including the red ring. The red ring can be moved. During development it became clear that Live does not always report the red ring correctly for group tracks and chains.

### Clips within the Red Ring  
Designed for touchscreen use. Clips and scenes can be triggered or stopped directly.

### Live Objects  
Displays relevant properties of current Live objects.

### Data Explorer  
Provides an overview of available data from Live, including the contents of received messages.

### System and State  
Displays the central status of Push2 and related metadata.

### Push2 Colors  
Shows the color tables used to convert `color_index` values to RGB.

### Push2 Device Banks  
Displays the parameter banks used by Push2 for instruments and effects.

### Browser  
Tracks selections in the Live browser. In practice this component is complex and not very usable. It will likely be replaced in Neoplay.

---

## Master Track Control

Push2Proxy does not directly control the Master track. Instead, control is routed through a Return track.

---

## Demo Live Set

A demo Live set is included:


/src - Max and Live/Test_Push2Proxy Project/Test_Push2Proxy.als


---

## Default Setup

On the Master track, the demo uses:

- Audio Effect Rack
- Compressor
- master_track_proxy.amxd
- master_track_signal.amxd

---

## Migration to Return Track

To move control to a Return track:

1. Copy all desired plugins from the Master track to the last Return track
2. Rename the Return track (for example: "Master")
3. Remove:


master_track_signal.amxd


4. Disable all plugins except the control components
5. Keep active:

- Audio Effect Rack
- master_track_proxy.amxd

---

## Result

After this setup:

- Return track volume controls Master volume
- Return track pan controls Master pan
- Send level controls Cue volume
- Audio Effect Rack macros control Master macros

The actual Master track is no longer directly visible to Push2Proxy, but remains fully functional.

---

## Notes

- The system relies on Ableton routing and requires some understanding of Live
- The demo is intended for exploration, not as a finished workflow
- Some behaviors (such as red ring reporting) are not fully consistent in Live