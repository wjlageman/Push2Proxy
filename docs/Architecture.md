# Architecture

This document describes the architecture of Push2Proxy and how it interacts with Ableton Live, Push2, and Max.

The system is built around intercepting and redirecting communication between these components, allowing Max to take control where needed.

---

## Overview

In a standard setup:


Push2 ⇄ Ableton Live ⇄ Control Surface Script


Push2Proxy introduces additional layers:


Push2 ⇄ Ableton Live ⇄ Push2Proxy ⇄ Max
⇅
libusb proxy


The goal is not to replace Live, but to insert control points where behavior can be intercepted, modified, or replaced.

---

## Design Principles

The system is built around a few key ideas:

- Do not break the existing Push2 ↔ Live integration
- Intercept communication instead of replacing it
- Allow selective control (pass-through or full takeover)
- Keep Max in control without losing stability

---

## Components

The system consists of three main components:

1. libusb proxy (low-level USB interception)
2. Push2Proxy (control surface interception)
3. Max (logic and rendering)

---

## 1. libusb Proxy

### Purpose

The libusb proxy replaces Ableton’s USB communication layer.

It allows direct access to the Push2 display from Max.

---

### Mechanism

Ableton loads:


libusb-1.0.dll


Push2Proxy replaces this with a custom version that:

- forwards calls to the original DLL
- intercepts relevant communication
- exposes display access to Max

---

### Capabilities

- Full display takeover
- Partial updates (rectangular regions)
- Overlay mode (Live + Max combined)

---

### Limitations

- Depends on internal Ableton behavior
- Sensitive to updates
- Requires correct DLL naming

---

## 2. Push2Proxy (Control Surface Layer)

### Purpose

Push2Proxy sits between:

- Ableton Live
- Push2 control surface script

It intercepts all communication between them.

---

### Data Flow


Live → Push2 (LEDs, display updates)
Push2 → Live (buttons, encoders, MIDI)


Push2Proxy intercepts both directions.

---

### Interception Model

Each message can be:

- Passed through unchanged
- Modified
- Fully blocked (“grabbed”)

---

### Example

LED update:

- Live sends LED color
- Push2Proxy intercepts
- Max can override or replace it
- Result is sent to Push2

---

### Capabilities

- Full LED control
- MIDI routing and transformation
- Custom behavior independent of Live
- Dynamic takeover of Push2 functions

---

## 3. Max Integration

### Purpose

Max acts as the central control layer.

It receives all intercepted data and determines behavior.

---

### Responsibilities

- UI rendering (Push2 display)
- Logic and routing
- State management
- Interaction with Live via LiveAPI

---

### Communication

Max communicates with:

- Push2Proxy (via intercepted data)
- libusb proxy (display control)
- Live (via LiveAPI)

---

## Red Ring Handling

### Purpose

The Push2 red ring defines the visible clip area.

Push2Proxy intercepts its position.

---

### Capabilities

- Detect clips inside the red ring
- Trigger and stop clips
- Move the red ring programmatically

---

### Limitations

Ableton does not always report red ring data correctly:

- Group tracks
- Chains

This behavior is outside the control of Push2Proxy.

---

## Display Pipeline

The Push2 display can be controlled in multiple modes:

1. Full takeover  
   Max fully controls the display

2. Partial update  
   Only specific regions are updated

3. Overlay  
   Live and Max share the display

---

## Control Modes

Push2Proxy allows dynamic switching between:

- Passive mode (pass-through)
- Active mode (intercept + modify)
- Full takeover

This allows gradual integration without breaking functionality.

---

## Stability Considerations

The system relies on:

- internal Ableton components
- control surface scripts
- USB communication

Because of this:

- updates may break compatibility
- careful installation is required
- debugging often involves multiple layers

---

## Development Notes

The system evolved incrementally:

- initial focus on display access
- then control surface interception
- then full integration with Max

The architecture reflects this layered approach.

---

## Relationship to Neoplay

Push2Proxy is not an end product.

It is a foundational component for the larger system:

**Neoplay**

In Neoplay:

- Push2 becomes the primary instrument
- Live acts as a sound engine
- Max provides control logic

Push2Proxy enables this by removing the limitations of the default Push2 workflow.

---

## Summary

Push2Proxy works by inserting itself into the communication paths between:

- Push2 hardware
- Ableton Live
- Control surface scripts

It does not replace these systems, but extends them.

The result is a flexible architecture where:

- Live continues to function
- Push2 remains responsive
- Max can take control when needed