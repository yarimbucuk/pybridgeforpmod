# Python Bridge for PenguinMod
# Tray app. Talks to the Scratch extension over localhost WebSocket.
# Session keys are ECDH P-256 + HKDF + AES-GCM. A new key is made for every connection.
# The secret is never sent. Only public keys and personal nonces go over the wire.

import asyncio
import base64
import hashlib
import json
import os
import queue
import re
import runpy
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime

FROZEN = getattr(sys, "frozen", False)
ROOT = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
COMMANDS = os.path.join(ROOT, "commands")
PORT = 8765
SITE = "https://pythonbridgeforpenguinmod.vercel.app"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
INFO = b"python-bridge-pm-v1"
MAX_FRAME = 1024 * 1024

os.makedirs(COMMANDS, exist_ok=True)

paused = False
sessions = {}
history = []
history_lock = threading.Lock()
ui_queue = queue.Queue()
loop_holder = {"loop": None}


def b64e(raw):
    return base64.b64encode(raw).decode("ascii")


def b64d(text):
    return base64.b64decode(text.encode("ascii"))


def safe_part(value):
    text = re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))
    if not text or text in (".", ".."):
        raise ValueError("invalid name")
    return text[:64]


def script_path(name, command):
    return os.path.join(COMMANDS, safe_part(name), safe_part(command) + ".py")


def read_script(name, command):
    path = script_path(name, command)
    if not os.path.isfile(path):
        return path, None
    with open(path, "r", encoding="utf-8") as handle:
        return path, handle.read()


def print_where():
    print("Python Bridge for PenguinMod")
    print("Installed at: " + ROOT)
    print("Commands: " + COMMANDS)
    print("Open: " + SITE)


def ensure_on_path():
    """Put this folder on the user PATH as the pybridgeforpmod command.
    User PATH does not need admin. If that fails, ask for admin and say why.
    """
    if sys.platform == "win32":
        return _ensure_windows_path()
    return _ensure_posix_path()


def _ensure_windows_path():
    """Put this folder on the user PATH. Ask for admin only if that fails."""
    try:
        _write_user_path()
        return True
    except OSError as error:
        _ask_admin_windows(str(error))
        return False


def _write_user_path():
    """Add this folder to the user PATH, and make sure .PY is in PATHEXT so that
    typing pybridgeforpmod runs pybridgeforpmod.py. No .cmd file is written.
    User PATH does not need admin.
    """
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, reg_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, reg_type = "", winreg.REG_EXPAND_SZ
        parts = [part for part in current.split(";") if part]
        if ROOT.lower() not in [part.lower() for part in parts]:
            parts.append(ROOT)
            winreg.SetValueEx(key, "Path", 0, reg_type or winreg.REG_EXPAND_SZ, ";".join(parts))
        # A user PATHEXT replaces the system one, so start from the effective value.
        exts = [ext for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if ext]
        if ".PY" not in [ext.upper() for ext in exts]:
            exts.append(".PY")
            winreg.SetValueEx(key, "PATHEXT", 0, winreg.REG_SZ, ";".join(exts))
    _broadcast_env()


def _broadcast_env():
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
        )
    except Exception:
        pass


def _ask_admin_windows(reason):
    message = (
        "Python Bridge could not add itself to your user PATH.\n\n"
        + reason
        + "\n\nProjects load commands by running pybridgeforpmod. "
        "If that command is not on PATH, installers cannot find this folder and commands will not install.\n\n"
        "An administrator prompt will open so the PATH entry can be written."
    )
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("Administrator permission needed", message)
        root.destroy()
    except Exception:
        print(message)
    try:
        import ctypes
        if FROZEN:
            # Run this exe elevated with --add-path, which only writes the PATH entry.
            params = "--add-path"
            target = sys.executable
        else:
            helper = os.path.join(ROOT, "_add_path_admin.py")
            with open(helper, "w", encoding="utf-8") as handle:
                handle.write("import sys\n")
                handle.write("sys.path.insert(0, %r)\n" % ROOT)
                handle.write("import pybridgeforpmod\n")
                handle.write("pybridgeforpmod._write_user_path()\n")
                handle.write("print('PATH updated')\n")
            params = '/c ""%s" "%s""' % (sys.executable, helper)
            target = "cmd.exe"
        ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, None, 1)
    except Exception as error:
        print("Could not ask for administrator permission: " + str(error))


def _ensure_posix_path():
    bindir = os.path.join(os.path.expanduser("~"), ".local", "bin")
    os.makedirs(bindir, exist_ok=True)
    shim = os.path.join(bindir, "pybridgeforpmod")
    script = os.path.join(ROOT, "pybridgeforpmod.py")
    body = "#!/bin/sh\n"
    body += "if [ -z \"$1\" ]; then\n"
    body += "  exec %s %s --where\n" % (shlex_quote(sys.executable), shlex_quote(script))
    body += "fi\n"
    body += "exec %s %s \"$@\"\n" % (shlex_quote(sys.executable), shlex_quote(script))
    try:
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(shim, 0o755)
    except OSError as error:
        _ask_admin_posix(str(error))
        return False
    _ensure_posix_profile(bindir)
    return True


def shlex_quote(text):
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _ensure_posix_profile(bindir):
    line = 'export PATH="$PATH:%s"\n' % bindir
    for name in (".profile", ".bashrc"):
        path = os.path.join(os.path.expanduser("~"), name)
        try:
            existing = ""
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    existing = handle.read()
            if bindir not in existing:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write("\n# Python Bridge for PenguinMod\n" + line)
        except OSError:
            pass


def _ask_admin_posix(reason):
    print("Could not write ~/.local/bin/pybridgeforpmod: " + reason)
    print("Administrator permission is needed so projects can find pybridgeforpmod.")
    print("Otherwise command installers cannot locate this folder and nothing is installed.")
    if shutil.which("sudo"):
        print("Retrying the shim install with sudo.")
        subprocess.call(["sudo", sys.executable, os.path.abspath(__file__), "--install-shim"])


def install_shim_only():
    if sys.platform == "win32":
        _ensure_windows_path()
    else:
        bindir = "/usr/local/bin" if os.access("/usr/local/bin", os.W_OK) else os.path.join(os.path.expanduser("~"), ".local", "bin")
        os.makedirs(bindir, exist_ok=True)
        shim = os.path.join(bindir, "pybridgeforpmod")
        script = os.path.join(ROOT, "pybridgeforpmod.py")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("exec %s %s \"$@\"\n" % (shlex_quote(sys.executable), shlex_quote(script)))
        os.chmod(shim, 0o755)


class SessionCrypto:
    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        self.ec = ec
        self.serialization = serialization
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.personal = os.urandom(32)
        self.aes = None
        self.send_n = 0
        self.recv_n = 0

    def public_b64(self):
        raw = self.private.public_key().public_bytes(
            self.serialization.Encoding.DER,
            self.serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return b64e(raw)

    def personal_b64(self):
        return b64e(self.personal)

    def finish(self, peer_public_b64, peer_personal_b64):
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        peer_key = self.serialization.load_der_public_key(b64d(peer_public_b64))
        shared = self.private.exchange(self.ec.ECDH(), peer_key)
        peer_personal = b64d(peer_personal_b64)
        salt = self._salt(peer_personal)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=INFO).derive(shared)
        self.aes = AESGCM(key)

    def _salt(self, peer_personal):
        # Overridden by the side that knows which nonce is the client's.
        return peer_personal

    def pack(self, obj):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        iv = os.urandom(12)
        aad = str(self.send_n).encode("ascii")
        self.send_n += 1
        ct = self.aes.encrypt(iv, json.dumps(obj).encode("utf-8"), aad)
        return {"t": "enc", "n": aad.decode("ascii"), "iv": b64e(iv), "ct": b64e(ct)}

    def unpack(self, packet):
        n = int(packet["n"])
        if n != self.recv_n:
            raise ValueError("rejected replayed or reordered message")
        self.recv_n += 1
        raw = self.aes.decrypt(b64d(packet["iv"]), b64d(packet["ct"]), str(n).encode("ascii"))
        return json.loads(raw.decode("utf-8"))


class ServerCrypto(SessionCrypto):
    def _salt(self, client_personal):
        return client_personal + self.personal


def run_script(name, command, parameters, data):
    path, source = read_script(name, command)
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "command": command,
        "parameters": parameters,
        "data": data,
        "path": path,
        "source": source,
        "ok": False,
        "result": "",
    }
    if source is None:
        record["result"] = "No python script installed for this command."
        _push_history(record)
        return record
    if FROZEN:
        argv = [sys.executable, "--run-script", path]
    else:
        argv = [sys.executable, os.path.abspath(__file__), "--run-script", path]
    creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            argv,
            input=json.dumps({"parameters": parameters, "data": data}),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=os.path.dirname(path),
            creationflags=creation,
        )
    except subprocess.TimeoutExpired:
        record["result"] = "Timed out."
        _push_history(record)
        return record
    stdout = proc.stdout or ""
    if "##BRIDGE_RESULT##" in stdout:
        record["ok"] = proc.returncode == 0
        record["result"] = stdout.split("##BRIDGE_RESULT##", 1)[1].strip()
    else:
        record["result"] = (proc.stderr or stdout or "Command failed.").strip()
    record["source"] = source
    _push_history(record)
    return record


def log_exception():
    try:
        with open(os.path.join(ROOT, "bridge.log"), "a", encoding="utf-8") as handle:
            handle.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n" + traceback.format_exc() + "\n")
    except OSError:
        pass


def run_script_cli(path):
    """Child process entry: read parameters and data from stdin, run run(), print the result."""
    payload = json.load(sys.stdin)
    ns = runpy.run_path(path)
    fn = ns.get("run")
    if not callable(fn):
        sys.stderr.write("script has no run(parameters, data)\n")
        sys.exit(2)
    value = fn(payload.get("parameters") or [], payload.get("data") or [])
    sys.stdout.write("\n##BRIDGE_RESULT##" + json.dumps(value, default=str))


def hide_console():
    """Tray mode only: hide the console window that a double-clicked exe opens."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _push_history(record):
    with history_lock:
        history.append(record)
        del history[:-200]


def allow_command(name, command):
    folder = os.path.join(COMMANDS, safe_part(name))
    os.makedirs(folder, exist_ok=True)
    path = script_path(name, command)
    created = False
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("def run(parameters, data):\n    return ''\n")
        created = True
    allow_path = os.path.join(folder, "_allow.json")
    allowed = []
    if os.path.isfile(allow_path):
        try:
            with open(allow_path, "r", encoding="utf-8") as handle:
                allowed = json.load(handle).get("commands", [])
        except Exception:
            allowed = []
    if command not in allowed:
        allowed.append(command)
    with open(allow_path, "w", encoding="utf-8") as handle:
        json.dump({"commands": allowed}, handle, indent=2)
    return path, created


async def read_frame(reader):
    header = await reader.readexactly(2)
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    masked = (header[1] & 0x80) != 0
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    if length > MAX_FRAME:
        raise ValueError("frame too large")
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return opcode, payload


async def write_frame(writer, text):
    raw = text.encode("utf-8")
    header = bytearray([0x81])
    size = len(raw)
    if size < 126:
        header.append(size)
    elif size < 65536:
        header.append(126)
        header.extend(size.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(size.to_bytes(8, "big"))
    writer.write(bytes(header) + raw)
    await writer.drain()


async def accept_http(reader, writer):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(1024)
        if not chunk:
            return False
        data += chunk
        if len(data) > 8192:
            return False
    text = data.decode("latin1")
    key = ""
    for line in text.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    if not key:
        return False
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
    writer.write((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
    ).encode("ascii"))
    await writer.drain()
    return True


async def send_enc(writer, crypto, obj):
    await write_frame(writer, json.dumps(crypto.pack(obj)))


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    if not peer or peer[0] not in ("127.0.0.1", "::1"):
        writer.close()
        return
    session_id = None
    try:
        if not await accept_http(reader, writer):
            writer.close()
            return
        crypto = ServerCrypto()
        while True:
            opcode, payload = await read_frame(reader)
            if opcode == 0x8:
                break
            if opcode != 0x1:
                continue
            message = json.loads(payload.decode("utf-8"))
            if message.get("t") == "hello":
                if paused:
                    await write_frame(writer, json.dumps({"t": "paused"}))
                    break
                crypto.finish(message["commonPublic"], message["personal"])
                await write_frame(writer, json.dumps({
                    "t": "welcome",
                    "commonPublic": crypto.public_b64(),
                    "personal": crypto.personal_b64(),
                }))
                continue
            if message.get("t") != "enc":
                continue
            obj = crypto.unpack(message)
            kind = obj.get("t")
            if kind == "bind":
                session_id = obj.get("id") or os.urandom(8).hex()
                sessions[session_id] = {
                    "name": str(obj.get("name") or "untitled"),
                    "crypto": crypto,
                }
                await send_enc(writer, crypto, {"t": "bound", "id": session_id})
                refresh_menu()
            elif kind == "rename":
                if session_id in sessions:
                    sessions[session_id]["name"] = str(obj.get("name") or "untitled")
                await send_enc(writer, crypto, {"t": "ok", "id": obj.get("id")})
                refresh_menu()
            elif kind == "run":
                if paused:
                    await send_enc(writer, crypto, {"t": "result", "id": obj.get("id"), "ok": False, "value": "Bridge is paused."})
                    continue
                name = str(obj.get("name") or "untitled")
                command = str(obj.get("command") or "")
                if session_id in sessions:
                    sessions[session_id]["name"] = name
                record = await asyncio.to_thread(
                    run_script, name, command, obj.get("parameters") or [], obj.get("data") or []
                )
                await send_enc(writer, crypto, {
                    "t": "result",
                    "id": obj.get("id"),
                    "ok": record["ok"],
                    "value": record["result"],
                })
            elif kind == "add":
                name = str(obj.get("name") or "")
                command = str(obj.get("command") or "")
                allowed = await asyncio.to_thread(ask_allow, name, command)
                path = ""
                created = False
                if allowed:
                    path, created = allow_command(name, command)
                await send_enc(writer, crypto, {
                    "t": "added",
                    "id": obj.get("id"),
                    "ok": bool(allowed),
                    "path": path,
                    "created": created,
                })
            else:
                await send_enc(writer, crypto, {"t": "error", "value": "unknown message"})
    except (asyncio.IncompleteReadError, ConnectionError, ValueError, json.JSONDecodeError):
        pass
    except Exception:
        log_exception()
    finally:
        if session_id in sessions:
            sessions.pop(session_id, None)
            refresh_menu()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def ask_allow(name, command):
    try:
        path = script_path(name, command)
    except ValueError:
        path = "(invalid name)"
    text = (
        'Allow this project to add command "%s" with name "%s"?\n\n'
        "This writes a python file on your computer:\n%s\n\n"
        "Only allow this if you trust the project."
    ) % (command, name, path)
    return _ask_on_ui(text)


def bring_to_front(on):
    try:
        ui_root.attributes("-topmost", on)
        if on:
            ui_root.lift()
            ui_root.focus_force()
    except Exception:
        pass


def _ask_on_ui(text):
    done = threading.Event()
    box = {"ok": False}

    def show():
        from tkinter import messagebox
        bring_to_front(True)
        box["ok"] = bool(messagebox.askyesno("Python Bridge verification", text, parent=ui_root))
        bring_to_front(False)
        done.set()

    ui_queue.put(show)
    done.wait(120)
    return box["ok"]


def open_site(_icon=None, _item=None):
    webbrowser.open(SITE)


def toggle_pause(_icon=None, _item=None):
    global paused
    paused = not paused
    refresh_menu()


def connected_label(_item=None):
    return "connected projects: %d" % len(sessions)


def pause_label(_item=None):
    return "Resume Bridge" if paused else "Pause Bridge"


def show_history(_icon=None, _item=None):
    ui_queue.put(_open_history)


def _open_history():
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(ui_root)
    win.title("Command history")
    win.attributes("-topmost", True)
    win.lift()
    win.focus_force()
    win.geometry("760x480")
    cols = ("time", "name", "command")
    tree = ttk.Treeview(win, columns=cols, show="headings", height=12)
    for col, title, width in (("time", "Time", 160), ("name", "Name", 180), ("command", "Command", 220)):
        tree.heading(col, text=title)
        tree.column(col, width=width)
    tree.pack(fill="x", padx=8, pady=8)
    text = tk.Text(win, height=14, wrap="word")
    text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    with history_lock:
        rows = list(history)
    ids = {}
    for index, row in enumerate(rows):
        iid = tree.insert("", "end", values=(row["time"], row["name"], row["command"]))
        ids[iid] = row

    def on_select(_event=None):
        selected = tree.selection()
        if not selected:
            return
        row = ids.get(selected[0])
        text.delete("1.0", "end")
        if not row:
            return
        if row.get("source") is None:
            text.insert("1.0", row["path"] + "\n\n(no python script installed for this command)")
        else:
            text.insert("1.0", row["path"] + "\n\n" + row["source"])

    tree.bind("<<TreeviewSelect>>", on_select)


def open_installer(_icon=None, _item=None):
    """Open installer.exe (exe build) or installer.py (script run) from the same folder."""
    if FROZEN:
        target = os.path.join(ROOT, "installer.exe")
        command = [target]
    else:
        target = os.path.join(ROOT, "installer.py")
        command = [sys.executable, target]
    if not os.path.isfile(target):
        _ask_on_ui_info("Installer not found", "No installer was found next to pybridgeforpmod:\n" + target)
        return
    try:
        subprocess.Popen(command, cwd=ROOT)
    except OSError as error:
        _ask_on_ui_info("Installer", "Could not open the installer: " + str(error))


def _ask_on_ui_info(title, text):
    def show():
        from tkinter import messagebox
        bring_to_front(True)
        messagebox.showinfo(title, text, parent=ui_root)
        bring_to_front(False)
    ui_queue.put(show)


def exit_app(icon=None, _item=None):
    try:
        if icon:
            icon.stop()
    except Exception:
        pass
    os._exit(0)


def build_menu():
    return pystray.Menu(
        pystray.MenuItem("Python Bridge for Penguinmod", open_site),
        pystray.MenuItem(connected_label, lambda _icon, _item: None, enabled=False),
        pystray.MenuItem("Command history", show_history),
        pystray.MenuItem("Open Installer", open_installer),
        pystray.MenuItem(pause_label, toggle_pause),
        pystray.MenuItem("Exit", exit_app),
    )


def refresh_menu():
    icon = loop_holder.get("icon")
    if not icon:
        return
    try:
        icon.menu = build_menu()
        icon.update_menu()
    except Exception:
        pass


def make_icon_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    try:
        draw.rounded_rectangle((2, 2, 62, 62), 14, fill=(48, 105, 152, 255))
    except Exception:
        draw.rectangle((2, 2, 62, 62), fill=(48, 105, 152, 255))
    draw.rectangle((14, 28, 50, 36), fill=(255, 212, 59, 255))
    draw.ellipse((10, 22, 26, 42), fill=(55, 118, 171, 255), outline=(255, 212, 59, 255), width=3)
    draw.ellipse((38, 22, 54, 42), fill=(55, 118, 171, 255), outline=(255, 212, 59, 255), width=3)
    return image


def start_tray():
    global pystray, ui_root
    hide_console()
    missing = []
    try:
        import pystray
    except Exception:
        missing.append("pystray")
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        missing.append("pillow")
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
    except Exception:
        missing.append("cryptography")
    if missing:
        print("Install dependencies first:")
        print(sys.executable + " -m pip install -r requirements.txt")
        print("Missing: " + ", ".join(missing))
        sys.exit(1)
    import tkinter as tk
    ui_root = tk.Tk()
    ui_root.overrideredirect(True)
    ui_root.geometry("1x1+0+0")
    ui_root.attributes("-alpha", 0.0)
    icon = pystray.Icon("python-bridge-pm", make_icon_image(), "Python Bridge for PenguinMod", build_menu())
    loop_holder["icon"] = icon
    threading.Thread(target=icon.run, daemon=True).start()
    print("Python Bridge for PenguinMod is running on ws://127.0.0.1:%d" % PORT)
    print("Installed at: " + ROOT)

    loop = asyncio.new_event_loop()
    loop_holder["loop"] = loop

    def thread_main():
        asyncio.set_event_loop(loop)

        async def serve():
            try:
                server = await asyncio.start_server(handle_client, "127.0.0.1", PORT)
            except OSError as error:
                print("Could not listen on port %d: %s" % (PORT, error))
                return
            async with server:
                await server.serve_forever()

        loop.run_until_complete(serve())

    threading.Thread(target=thread_main, daemon=True).start()

    def pump():
        while True:
            try:
                job = ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception:
                log_exception()
        ui_root.after(30, pump)

    ui_root.after(30, pump)
    ui_root.mainloop()


def main():
    args = sys.argv[1:]
    if args[:1] == ["--run-script"] and len(args) > 1:
        run_script_cli(args[1])
        return
    if args[:1] == ["--add-path"]:
        _write_user_path()
        return
    if args[:1] == ["--prefix"]:
        print(ROOT)
        return
    if args[:1] == ["--where"] or args[:1] == ["--install-shim"]:
        if args[:1] == ["--install-shim"]:
            install_shim_only()
        print_where()
        return
    if not args or args[:1] == ["--tray"]:
        ensure_on_path()
        start_tray()
        return
    print("Unknown arguments. Run with no arguments to start the bridge.")
    print("  --where    show where it is installed")
    print("  --prefix   print the install folder only")


if __name__ == "__main__":
    main()
