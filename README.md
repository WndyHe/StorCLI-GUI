# StorCLI GUI

[![Build and Release](https://github.com/WndyHe/StorCLI-GUI/actions/workflows/build-release.yml/badge.svg)](https://github.com/WndyHe/StorCLI-GUI/actions/workflows/build-release.yml)

Windows GUI for Broadcom MegaRAID StorCLI, designed for day-to-day controller,
virtual drive, physical drive, enclosure and firmware management.

The GUI is a front-end. It does **not** redistribute Broadcom's `storcli64.exe`.
Download a StorCLI version compatible with your controller and place
`storcli64.exe` beside the GUI executable.

## Features

- Controller overview with health, firmware, hardware and resource summaries.
- Localized controller detail view with searchable properties and raw JSON.
- MSM-style **Modify Drive Group** support with RAID migration, member-drive
  addition, disk-count-aware RAID choices and capacity expansion.
- Physical drive actions: locate, rebuild, state changes, hot spare, SMART,
  error counters and firmware update.
- Searchable tables with state filters, horizontal scrolling, sorting and CSV export.
- Structured controller event view with severity filters and raw-log fallback.
- Dangerous-operation mutex, controller context protection and long-task progress.
- Administrator elevation manifest and light/dark-safe Windows redraw handling.

## Requirements

- Windows 7/8/8.1/10/11 x64 or Windows Server 2008 R2 x64 to Windows Server 2025 x64
- Administrator privileges for controller discovery and management.
- A compatible Broadcom `storcli64.exe` binary.

## Quick start

1. Download `StorCLI_GUI.exe` from the latest GitHub Release.
2. Place it in a writable directory.
3. Put a compatible `storcli64.exe` in the same directory, or choose its path in
   the GUI's **StorCLI: Settings...** dialog.
4. Run `StorCLI_GUI.exe` and accept the administrator permission prompt.

The GUI displays the exact StorCLI command and raw output for every operation.
Review the target controller, enclosure and slot before confirming any operation
that changes controller configuration or overwrites data.

## Run from source

Official builds use Python 3.15 with Tk 9.0. The source remains compatible with
Python 3.8 or newer with Tkinter.

```powershell
python storcli_gui.py
```

Alternatively, run `StorCLI-GUI.bat`.

## Build

```powershell
python -m pip install pyinstaller
python tools/build_windows.py
```

The official release executable is built with local Python 3.15 and the same
version is used by GitHub Actions.

The build script reads `APP_VERSION` and `APP_ICON_B64` from `storcli_gui.py`,
generates the Windows version resource and ICO, then creates:

```text
dist/StorCLI_GUI.exe
```

GitHub Actions runs static checks and a Windows build for every push and pull
request. Pushing a `v*` tag also uploads the executable to the matching GitHub
Release.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the complete version history.

## Safety notes

- Firmware flashing and controller configuration changes are high-risk operations.
- Do not power off or remove drives during firmware updates, initialization or rebuilds.
- The GUI prevents overlapping dangerous operations and blocks closing while a task
  is active, but StorCLI itself remains the final authority on hardware validity.
- Validate operations on non-critical hardware first.

## Third-party software

Broadcom StorCLI is a separate third-party product and remains subject to
Broadcom's own license terms. This repository only provides the GUI front-end and
does not include the StorCLI binary.

## License

The GUI source code in this repository is licensed under the Apache License 2.0.
See [LICENSE](LICENSE).
