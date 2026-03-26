## Overview

Installation consists of four main steps:


1\. Replace Ableton’s libusb driver with the proxy version

2\. Install the required Max external

3\. Configure Ableton startup options

4\. Replace the Push2 control surface script


Each step is described below.


## 1. Install libusb Proxy


Ableton Live uses its own version of `libusb-1.0.dll`. This project replaces that file with a proxy version.

A typical Ableton installation directory looks like:

C:\\ProgramData\\Ableton\\Live 12 Suite\\Program

### Steps

1\. Navigate to the Ableton Live Program folder

2\. Locate the file:

libusb-1.0.dll

3\. Rename this file to:

libusb-1.0.original.dll

\*\*Important:\*\*  

The filename must match exactly. The proxy depends on this exact name.

4\. Copy the file from:

/External/libusb-1.0.dll

into the Ableton Live Program folder.

\---

### Optional: Disable Push 3 interference

In some cases Push2 may not behave correctly due to Push3 drivers.

You can disable this by renaming:

Push3.exe → Push3.exe#

This prevents Push3 drivers from interfering with Push2.

\---

## 2. Install Max External

This project includes a Max external:

wjl\_libusb\_proxy.mxe64

This external must be installed in both standalone Max and Max for Live.

---

### Standalone Max locations

C:\\Program Files\\Cycling '74\\Max 9\\resources\\externals

C:\\Program Files\\Cycling '74\\Max 8\\resources\\externals

### Max for Live location (inside Ableton)

C:\\ProgramData\\Ableton\\Live 12 Suite\\Resources\\Max\\resources\\externals

---

### Steps

1\. In each externals folder, create a new folder:

wjl\_libusb\_proxy

2\. Copy the file:

/External/wjl\_libusb\_proxy.mxe64

into this folder.

Repeat this for all relevant Max installations.

---

## 3. Configure Ableton Options

Ableton needs to be configured to use the legacy Push2 script.

Navigate to:

C:\\Users<YourUser>\\AppData\\Roaming\\Ableton\\Live 12.x.x\\Preferences

Open or create the file:

Options.txt

Add the following line:

\-Push2UseLegacyScript

A sample `Options.txt` file is included in the `/External` folder.

---

## 4. Install Custom Push2 Control Surface

Push2Proxy requires a modified Push2 control surface script.

Navigate to:

C:\\ProgramData\\Ableton\\Live 12 Suite\\Resources\\MIDI Remote Scripts

Open the folder:

Push2

---


### Steps

1\. Create a backup folder:

Push2Original

2\. Move all existing files from the `Push2` folder into `Push2Original`

3\. Copy the contents from:

src - Push2 control surface

into the `Push2` folder

---

### Important

Ableton updates may overwrite this folder. It is recommended to keep a backup of your modified version.

---

## 5. Verify Installation

Start Ableton Live.

If the installation is successful:

- Push2 will start with a modified screen

- Push2Proxy is active

---

## Notes

- This setup modifies internal Ableton components

- Keep backups of original files

- Installation is reversible by restoring original files
