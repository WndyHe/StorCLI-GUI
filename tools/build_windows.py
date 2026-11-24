"""Build the Windows StorCLI GUI executable with generated icon and version data."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "storcli_gui.py"
BUILD_ROOT = ROOT / "build"
GENERATED = BUILD_ROOT / "generated"
DIST = ROOT / "dist"
ICON = GENERATED / "storcli_gui.ico"
VERSION_FILE = GENERATED / "storcli_version.txt"
VERSION_TEXT = BUILD_ROOT / "app-version.txt"


def load_source():
    spec = importlib.util.spec_from_file_location("storcli_gui_build", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def version_parts(version: str) -> tuple[int, int, int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", version)[:4]]
    return tuple((numbers + [0, 0, 0, 0])[:4])


def write_version_file(version: str):
    major, minor, patch, build = version_parts(version)
    VERSION_FILE.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [
          StringStruct('CompanyName', 'Windy He'),
          StringStruct('FileDescription', 'StorCLI GUI - Broadcom RAID management GUI'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'StorCLI_GUI'),
          StringStruct('LegalCopyright', 'Made By Windy He'),
          StringStruct('OriginalFilename', 'StorCLI_GUI.exe'),
          StringStruct('ProductName', 'StorCLI GUI'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def build():
    module = load_source()
    version = str(module.APP_VERSION)
    GENERATED.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    ICON.write_bytes(base64.b64decode(module.APP_ICON_B64))
    write_version_file(version)
    VERSION_TEXT.write_text(version, encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--name",
        "StorCLI_GUI",
        "--icon",
        str(ICON),
        "--version-file",
        str(VERSION_FILE),
        "--add-data",
        f"{ROOT / 'LICENSE'};.",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD_ROOT / "pyinstaller"),
        "--specpath",
        str(BUILD_ROOT / "spec"),
        str(SOURCE),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    executable = DIST / "StorCLI_GUI.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller did not create dist/StorCLI_GUI.exe")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    print(f"Built StorCLI_GUI.exe v{version}")
    print(f"SHA256={digest}")


if __name__ == "__main__":
    build()
