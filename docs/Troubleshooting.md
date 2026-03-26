# Troubleshooting



This document lists common issues and practical solutions when working with Push2Proxy.



Installation is manual and modifies internal Ableton components, so problems are usually related to configuration, file placement, or version mismatches.



---



## Push2 does not respond



### Check libusb installation



Verify that:



- `libusb-1.0.dll` in the Ableton Program folder has been replaced

- The original file has been renamed to:





libusb-1.0.original.dll





If this is not correct, Push2Proxy will not work.



---



### Check Push3 interference



Push3 drivers may interfere with Push2.



Try renaming:





Push3.exe → Push3.exe#





Restart Ableton and test again.



---



## Push2 starts normally (no modified screen)



This usually means the custom control surface is not active.



### Check control surface installation



Verify that:



- The original `Push2` folder has been backed up

- The modified control surface files are copied into:





C:\\ProgramData\\Ableton\\Live 12 Suite\\Resources\\MIDI Remote Scripts\\Push2





---



### Check Options.txt



Make sure the following line is present:





-Push2UseLegacyScript





Location:





C:\\Users<YourUser>\\AppData\\Roaming\\Ableton\\Live 12.x.x\\Preferences\\Options.txt





Restart Ableton after making changes.



---



## Max external not found



If Max reports missing objects:



### Check installation



Verify that:





wjl\_libusb\_proxy.mxe64





is located in:





...Max\\resources\\externals\\wjl\_libusb\_proxy





This must be installed for:



- Max standalone (Max 9 / Max 8 if used)

- Max for Live (inside Ableton)



---



## Demo does not work correctly



### Check Max version



This project is designed for:



- Ableton Live 12

- Bundled Max 9



Older versions (Max 8 or older Live versions) may behave differently or fail.



---



### Check device loading



Make sure:



- `Push2Proxy\_Max9.amxd` is loaded correctly

- No errors appear in the Max console



---



## Red ring behaves incorrectly



This is a known limitation.



Ableton Live does not always report the red ring correctly, especially with:



- Group tracks

- Device chains



This is not a bug in Push2Proxy.



---



## General instability



Because this setup modifies internal components:



- Ableton updates may overwrite files

- Version mismatches may occur

- Unexpected behavior is possible



If things stop working:



1\. Re-check all installation steps

2\. Restore backups if needed

3\. Reinstall components



---



## About support



This project was developed with assistance from ChatGPT.



In many cases, ChatGPT can provide better and faster technical guidance than the author can offer remotely, especially for:



- debugging setup issues

- understanding Max or JavaScript behavior

- exploring modifications



If you run into problems, it is recommended to:



- clearly describe your setup

- include error messages

- include relevant code snippets



---



## Reporting issues



If you encounter:



- reproducible bugs

- unexpected behavior

- technical limitations



Please report them on GitHub.



Include:



- Ableton version

- Max version

- Windows version

- Clear steps to reproduce the issue



Constructive reports are useful and appreciated.



---



## Final note



This is a complex system built on top of multiple layers (Ableton, Max, USB, control surfaces).



Some rough edges are unavoidable.



If something behaves strangely, assume first that it is a configuration issue before assuming it is a bug.



