# Flow Device Agent — Windows Packaging (Gate K.2)

## Overview

The Flow Device Agent is packaged as a self-contained Windows executable
(`flow-agent.exe`) using PyInstaller. No Python installation is required on
the end-user's machine.

## Prerequisites (build machine only)

```
Python 3.11 (recommended — PyInstaller 6.x certified support)
pip install pyinstaller pywin32 pystray pillow websockets aiohttp
```

> **Note:** Python 3.14 is used for the server-side development environment.
> A separate Python 3.11 is used for packaging — this is standard practice
> for desktop application distribution.

## Building

From the project root:

```bat
py -3.11 agent\build\build.py
```

Output: `dist\flow-agent\flow-agent.exe` (+ supporting DLLs and PYDs)

Alternatively, invoke PyInstaller directly:

```bat
py -3.11 -m PyInstaller agent\build\flow_agent.spec --noconfirm
```

## Installing on a Windows machine

1. Build the package as above (or copy a pre-built `dist\flow-agent\` folder).

2. Run the installer:

```bat
agent\build\install.bat
```

This copies the application to `%LOCALAPPDATA%\FlowAgent\app\`.

To also register the agent to start on Windows login:

```bat
agent\build\install.bat --startup
```

## Enrolling a device

After installation, enroll this device with your Flow server:

```bat
"%LOCALAPPDATA%\FlowAgent\app\flow-agent.exe" enroll ^
    --server wss://your-flow-server.example.com ^
    --token YOUR-ENROLLMENT-TOKEN ^
    --name "My PC"
```

The enrollment token is generated from the Flow web UI.

**Security:** The device credential is stored in
`%APPDATA%\FlowAgent\device.enc` using Windows DPAPI — encrypted with
the Windows user account key. It is never stored in plaintext and is never
exposed to the browser.

## Starting the agent

```bat
"%LOCALAPPDATA%\FlowAgent\app\flow-agent.exe" run
```

A system tray icon appears showing connection status.

## Autostart management

Register to start on login:

```bat
"%LOCALAPPDATA%\FlowAgent\app\flow-agent.exe" startup "%LOCALAPPDATA%\FlowAgent\app"
```

Remove autostart:

```bat
"%LOCALAPPDATA%\FlowAgent\app\flow-agent.exe" remove-startup
```

## Uninstalling

```bat
agent\build\uninstall.bat
```

This:
1. Clears stored device credentials
2. Removes the autostart registry entry
3. Removes `%LOCALAPPDATA%\FlowAgent\app\`
4. (Optional, prompted) Removes `%APPDATA%\FlowAgent\`

No administrator privileges are required for any of these steps.

## Emergency failsafe

The emergency hotkey **Ctrl+Shift+Alt+F12** releases all input hooks
immediately and stops remote control. This is network-independent — it
works even if the WebSocket connection is down.

## Security notes

- Credentials are DPAPI-encrypted at rest (user-scope)
- No credentials, tokens, or server URLs are baked into the `.exe`
- The server URL is set at enrollment time and stored non-secretly in
  `%APPDATA%\FlowAgent\config.json`
- The agent never logs key codes (vk/scan) or raw mouse payloads
- The tray icon provides visual indication when Remote Control is ACTIVE

## File layout

```
dist\flow-agent\
  flow-agent.exe        ← main executable
  python3xx.dll         ← embedded Python interpreter
  *.pyd                 ← C extension modules (win32crypt, _imaging, …)
  *.dll                 ← Windows runtime DLLs
  _internal\            ← bundled Python stdlib + packages
```

## Gate classification

| Check | Status |
|-------|--------|
| PyInstaller spec | ✅ Provided |
| Build script | ✅ Provided |
| Installer/uninstaller | ✅ Provided |
| DPAPI storage | ✅ Existing (unchanged) |
| Autostart (Registry) | ✅ startup / remove-startup commands |
| Failsafe preservation | ✅ ctypes hooks unchanged |
| .exe built | Verify with `build.py` |
| .exe runs (`version`) | Verify on target machine |
| End-to-end (enroll→run→control) | Hardware test required |
