"""One-time setup for File Converter.

Creates a private Python environment inside this folder, installs the
converters into it, and puts a "File Converter" shortcut on your desktop.
Run it again at any time to repair or update. Remove everything with:

    python install.py --uninstall
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
VENV = APP / ".venv"
MAIN = APP / "file_converter.py"
ICON_PNG = APP / "assets" / "icon.png"
ICON_ICO = APP / "assets" / "icon.ico"
NAME = "File Converter"


def say(msg=""):
    print(msg, flush=True)


def fail(msg):
    say()
    say("Setup stopped: " + msg)
    sys.exit(1)


def venv_python(gui=False):
    if os.name == "nt":
        return VENV / "Scripts" / ("pythonw.exe" if gui else "python.exe")
    return VENV / "bin" / "python"


def check_python():
    if sys.version_info < (3, 9):
        fail(f"Python 3.9 or newer is needed; this is {sys.version.split()[0]}. "
             "Get a newer one from https://www.python.org/downloads/")
    try:
        import tkinter
        tkinter.Tcl()
    except Exception:
        if sys.platform == "darwin":
            hint = ("Install Python from https://www.python.org/downloads/ (it includes Tk), "
                    "or run: brew install python-tk")
        elif os.name == "nt":
            hint = "Re-run the Python installer, choose Modify, and tick 'tcl/tk and IDLE'."
        else:
            hint = "Install your system's Tk package, e.g. sudo apt install python3-tk"
        fail("this Python has no Tk (needed for the app window). " + hint)


def install_packages():
    if not venv_python().exists():
        say("Creating a private Python environment in this folder…")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    py = str(venv_python())
    say("Installing the converters (about 700 MB of disk space; this can take a few minutes)…")
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                           "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                           "-r", str(APP / "requirements.txt")])


def desktop_dir():
    if os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "[Environment]::GetFolderPath('Desktop')"],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            if out:
                return Path(out)  # follows OneDrive's Desktop redirection
        except (OSError, subprocess.SubprocessError):
            pass
    elif sys.platform != "darwin" and shutil.which("xdg-user-dir"):
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    return Path.home() / "Desktop"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def windows_shortcuts(remove=False):
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    places = [desktop_dir(), appdata / "Microsoft" / "Windows" / "SendTo",
              appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    links = [p / f"{NAME}.lnk" for p in places]
    if remove:
        for link in links:
            link.unlink(missing_ok=True)
        return links
    script = ["$ws = New-Object -ComObject WScript.Shell"]
    for link in links:
        script += [
            f"$s = $ws.CreateShortcut({ps_quote(link)})",
            f"$s.TargetPath = {ps_quote(venv_python(gui=True))}",
            f"$s.Arguments = {ps_quote(chr(34) + str(MAIN) + chr(34))}",
            f"$s.WorkingDirectory = {ps_quote(APP)}",
            f"$s.IconLocation = {ps_quote(str(ICON_ICO) + ',0')}",
            "$s.Description = 'Convert documents, images, video, audio and more'",
            "$s.Save()",
        ]
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "; ".join(script)], check=True, capture_output=True, text=True)
    return links


def mac_app(remove=False):
    bundle = desktop_dir() / f"{NAME}.app"
    if remove:
        shutil.rmtree(bundle, ignore_errors=True)
        return [bundle]
    shutil.rmtree(bundle, ignore_errors=True)
    macos = bundle / "Contents" / "MacOS"
    resources = bundle / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    launcher = macos / "FileConverter"
    launcher.write_text(f'#!/bin/bash\nexec "{venv_python()}" "{MAIN}" "$@"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    info = {
        "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleExecutable": "FileConverter",
        "CFBundleIdentifier": "local.file-converter", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0", "CFBundleIconFile": "icon.icns",
        "NSHighResolutionCapable": True,
        # Lets you drop any file onto the app icon.
        "CFBundleDocumentTypes": [{"CFBundleTypeName": "Any file", "CFBundleTypeRole": "Viewer",
                                   "LSHandlerRank": "Alternate",
                                   "LSItemContentTypes": ["public.data", "public.content"]}],
    }
    with open(bundle / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump(info, fh)
    try:
        subprocess.check_call([str(venv_python()), "-c",
                               "import sys; from PIL import Image; "
                               "Image.open(sys.argv[1]).save(sys.argv[2])",
                               str(ICON_PNG), str(resources / "icon.icns")])
    except (OSError, subprocess.CalledProcessError):
        say("  (couldn't make the app icon; the app still works)")
    return [bundle]


def linux_launchers(remove=False):
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    files = [apps / "file-converter.desktop", desktop_dir() / "file-converter.desktop"]
    if remove:
        for f in files:
            f.unlink(missing_ok=True)
        return files
    entry = (
        "[Desktop Entry]\nType=Application\nName=File Converter\n"
        "Comment=Convert documents, images, video, audio and more\n"
        f'Exec="{venv_python()}" "{MAIN}" %F\nIcon={ICON_PNG}\nTerminal=false\n'
        "Categories=Utility;\n"
    )
    made = []
    for f in files:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(entry)
            f.chmod(0o755)
            if shutil.which("gio"):
                subprocess.run(["gio", "set", str(f), "metadata::trusted", "true"],
                               capture_output=True)
            made.append(f)
        except OSError as exc:
            say(f"  couldn't write {f}: {exc}")
    return made


def make_shortcuts(remove=False):
    if os.name == "nt":
        return windows_shortcuts(remove)
    if sys.platform == "darwin":
        return mac_app(remove)
    return linux_launchers(remove)


def uninstall():
    for path in make_shortcuts(remove=True):
        say(f"Removed {path}")
    shutil.rmtree(VENV, ignore_errors=True)
    say(f"Removed {VENV}")
    say("File Converter is uninstalled. You can now delete this folder.")


def main():
    say(f"{NAME} setup")
    say("=" * 40)
    if "--uninstall" in sys.argv:
        return uninstall()
    check_python()
    try:
        install_packages()
    except subprocess.CalledProcessError:
        fail("installing the converters failed (see the messages above). "
             "Check your internet connection and run setup again.")
    say()
    subprocess.call([str(venv_python()), str(MAIN), "--check"])
    say()
    try:
        for path in make_shortcuts():
            say(f"Shortcut: {path}")
    except Exception as exc:
        say(f"Couldn't create the desktop shortcut ({exc}).")
        say(f'Start the app with: "{venv_python(gui=True)}" "{MAIN}"')
    say()
    say(f"All set. Open '{NAME}' from your desktop.")
    if os.name == "nt":
        say("Tip: you can also drop files onto the desktop icon, or right-click any file and "
            "choose Send to > File Converter.")
    elif sys.platform == "darwin":
        say("Tip: you can also drop files onto the app icon.")
    say("Keep this folder where it is: the shortcut runs the app from here.")


if __name__ == "__main__":
    main()
