# Conceptual Layers

Push2 Hardware

│

▼

Ableton Live

│

▼

libusb Proxy (C++)

│

▼

Named Pipe

│

▼

wjl_libusb_proxy (Max external)

│

▼

Max / Jitter / JS

│

▼

User Interface & Logic



# Project Structure (Push2Proxy)

Push2Proxy (Published)
│
├── README.md
├── LICENCE.txt
│
├── docs/                        -> Documentation
│   ├── Architecture.md
│   ├── installation.md
│   ├── proxy_commands.md
│   ├── Troubleshooting.md
│   └── Usage demo app.md
│
├── External/                    -> Files required for installation
│   ├── libusb-1.0.dll           -> Proxy DLL (replaces Ableton version)
│   ├── wjl_libusb_proxy.mxe64   -> Max external
│   └── Options.txt              -> Ableton configuration
│
├── src - Max and Live/          -> Demo and Max for Live devices
│   ├── Push2Proxy_Max9.amxd     -> Main demo device
│   ├── master_track_proxy.amxd
│   ├── master_track_signal.amxd
│   ├── automation.v8.js
│   ├── tabstrip.js
│   └── Test_Push2Proxy Project/ -> Example Live set
│
├── src - Push2 control surface/ -> Modified Ableton control surface (Python)
│   ├── Push2Proxy.py
│   ├── IoManager.py
│   ├── UDP.py
│   ├── observers/
│   ├── builtins/
│   └── modules/
│
├── src - Push2LibusbProxy/      -> C++ libusb proxy (DLL)
│   ├── Push2LibusbProxy.sln
│   ├── LibusbProxy.cpp
│   ├── NamedPipeServer.cpp
│   ├── FrameHandler.cpp
│   └── Resources/
│
└── src - wjl_libusb_proxy/      -> Max external (C++)
    ├── wjl_libusb_proxy.sln
    ├── jit_matrix_handler.cpp
    ├── NamedPipeClient.cpp
    ├── Takeover.cpp
    └── src/
