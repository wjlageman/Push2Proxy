# Push2Proxy

Push2Proxy is a component that allows full software control over the Ableton Push2 from Max, and indirectly also over Live.

It does not do anything musical by itself.

Windows only.

---

## Overview

Push2Proxy sits between Ableton Live and the Push2 control surface and allows you to intercept, modify, or completely replace communication between them.

This enables:

- Full control over Push2 LEDs and display
- Interception of MIDI data
- Control over the red ring and clip launching
- Integration with Max / Max for Live

---

## Background

To get straight to the point: Push2Proxy is a component that allows you to fully take over the Ableton Push2 from Max in software, and indirectly also control Live. It does not do anything musical by itself. Windows only. All source code is included and is open source, but the project consists of a mix of C++, Python, JavaScript and Max. You need some knowledge of these languages to really work with it.

On the other hand: if you have a bit of technical intuition, you can often use ChatGPT to help you. ChatGPT also contributed significantly to the codebase. Without it, this project would not have reached this level. But the other way around, ChatGPT would not have been able to do it without strict direction.

The original motivation for this project was different. I was working on further optimizing the Korg Electribe with the Hacktribe firmware. The device still feels modern, but eventually I ran into the physical limits of the hardware: limited interface, limited processing, and little room to experiment further.

Instead of pushing against those limits, I decided to move forward: Ableton Live + Push2, with Max in control. In this model, many of the limitations of dedicated hardware disappear. In principle: the sky is the limit.

The larger design has the codename Neoplay. The goal is to build a groovebox, but not just any groovebox. The sound engine is Ableton Live 12.2.5. Control is handled through Push2, and Max / MaxForLive makes it all work.

The idea is that you no longer have to switch between Push2 and Live with mouse and keyboard. Everything is done on Push2, except typing names. The main Live screen can be turned off. Push2 becomes your instrument: no distractions, full focus on what you are doing.

Push was originally designed as an extension of Live and had to support all of Live’s functionality. Neoplay turns that around. You make music on Push2, without mouse, without keyboard, and without Session or Arrangement View. Live provides the sound. Max makes it possible.

Push2Proxy can be used both in Max for Live and in Max standalone. This mainly depends on how you want to work with Live. Max for Live has the advantage that everything is stored inside the Live set. Max standalone has the advantage that you can close and restart Live without software issues.

Technically, the strong coupling between Push2 and Live remains the foundation. On top of that, additional layers are introduced to bring Max in control.

⭐ Support

If you find this project useful, giving it a star on GitHub is appreciated.

It is a simple way to show that the project is being used, and it helps to decide how much time to invest in further development — including Push2Proxy itself and the next stage, Neoplay.

---

## Architecture

### Libusb Proxy

Max can take over the Push2 display. This can be a full takeover or limited to rectangular regions. It can completely replace the display, or act as an overlay where Live’s screen is still partially visible.

---

### Push2Proxy

A control layer is placed between Live and the Push2 control surface. All messages from Live to Push2 are intercepted and sent to Max. All MIDI data from Push2 to Live, and from Live to the Push2 LEDs, are also intercepted.

You can choose to pass messages through unchanged, or “grab” them so they never reach their original destination. This allows you to take full control. For example, you can set LED colors and brightness yourself, or send MIDI messages from Max to Push2 and Live.

---

### Red Ring

The position of the Push2 red ring is also intercepted. This allows you to know exactly which clips are inside the red ring. From Max you can trigger or stop clips, and you can also move the red ring yourself in small or larger steps.

---

## Demo Application

This component is released as a standalone project for curious developers who want to see how this is implemented technically. A demo application is included with several components:

### LED Demo  
Shows the colors and behavior of LEDs, buttons, and encoders.

### Parameters  
Displays current parameter values, including minimum and maximum.

### Liveset with Red Ring  
Displays the full Live set on the Push2 screen, including the red ring. The red ring can also be moved. During development it became clear that Live does not always display the red ring correctly for group tracks and chains.

### Clips within the Red Ring  
Designed for touchscreen use. Clips and scenes can be triggered or stopped directly.

### Live Objects  
Displays relevant properties of current Live objects.

### Data Explorer  
Overview of available data from Live, including the contents of received messages.

### System and State  
Central status of Push2 and related metadata.

### Push2 Colors  
Color tables used to convert `color_index` values to RGB for LEDs and the Push2 display.

### Push2 Device Banks  
The parameter banks used by Push2 for instruments and effects.

### Browser  
Tracks selections in the Live browser. In practice this component is quite confusing and offers too many options to be truly usable. For Neoplay, a simpler and more focused alternative will likely be developed.

---

## Status

It took about six months to make all of this work. Developing the next stage — Neoplay itself — will likely take several more months.

---

## Documentation

See the `/docs` folder for:

- Installation
- Usage
- Architecture details

---

## License

This project is released as source-available freeware.

- Non-commercial use is allowed
- Commercial use requires permission
- Redistribution or public forks are not allowed without permission

See the LICENSE file for details.

---

## Notes

Even if you do not plan to use Push2Proxy directly, the project may still be of interest. It contains a number of technical solutions and hacks that may be useful or inspiring if you are working with Max.

A design of this size inevitably contains shortcomings, mistakes, and bugs.

If you find something, feel free to report it.