# Python Bridge for PenguinMod

Run Python code on your own computer from a PenguinMod project.

Site: https://pythonbridgeforpenguinmod.vercel.app/

A small Scratch extension talks to a tray app on your machine over a local, encrypted connection. The tray app runs the Python command you wrote and sends the result back to Scratch.

- **Local only:** the tray app accepts connections from `127.0.0.1` only.
- **Encrypted:** every session uses a new key. The secret key never travels over the network.
- **Per project:** each Scratch project only sees its own command folder.
- **Approval:** a project cannot add a command file without your confirmation.

## Contents

- [The parts](#the-parts)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Scratch blocks](#scratch-blocks)
- [Writing a command](#writing-a-command)
- [Command builder](#command-builder)
- [Main app (tray app)](#main-app-tray-app)
- [Installer](#installer)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [License](#license)

## The parts

| File | What it is | What it does |
|---|---|---|
| `pybridgeforpmod.py` | **Main app** (tray app) | Runs in the background with a tray icon. Accepts connections from Scratch, runs your command scripts, asks for approval before a project adds a command, and keeps a command history. Adds itself to your PATH on first start. |
| `installer.py` | **Installer** | A separate window. Reads a `.config` file and copies its commands into the main app's `commands/` folder. Can also remove installed commands. It does not run anything itself. |
| `builder.html` | **Command builder** | A web page you open in a browser. Creates projects, lets you write the commands and their Python code, and exports a `.config` file. |
| `scratch/pythonBridge.js` | **Scratch extension** | Loaded into PenguinMod as an unsandboxed extension. Provides the blocks. |

In short: you build a `.config` in the builder, install it with the installer, and the main app runs it when your Scratch project asks.

## How it works

```text
PenguinMod project ──(encrypted WebSocket, 127.0.0.1:8765)──> main app ──> commands/<project>/<command>.py
```

1. The extension connects and both sides agree on a session key.
2. The project calls `run` with a command name, parameters and data.
3. The main app reads `commands/<project name>/<command>.py` and runs its `run(parameters, data)` function.
4. The return value is sent back and shows up in `result of`, `last python result`, and the tray's command history.

## Requirements

| Item | Version | Used for |
|---|---|---|
| Python | 3.9 minimum, 3.10 to 3.12 recommended | The main app and your command scripts |
| `cryptography` | `>=42.0.0` | Session encryption |
| `pystray` | `>=0.19.5` | Tray icon and menu |
| `pillow` | `>=10.0.0` | Tray icon image |
| `tkinter` | Included with Python | Dialogs and windows |

On Debian/Ubuntu, install tkinter with `sudo apt install python3-tk`.

Install the Python packages:

```bash
pip install -r requirements.txt
```

The installer uses only the standard library, so it needs tkinter but none of the packages above. The command builder is a plain HTML page.

The project was built and tested on Python 3.10. Newer Python versions may work, but check that your versions of `cryptography` and `pystray` support them.

## Quick start

1. **Start the main app**

   ```bash
   python pybridgeforpmod.py
   ```

   A tray icon appears. The app adds a `pybridgeforpmod` command to your PATH. Check it with `pybridgeforpmod --where`.

2. **Create your commands** by opening `builder.html` in a browser. See [Command builder](#command-builder).

3. **Install them** by running `installer.py`. See [Installer](#installer).

4. **Load the extension** in PenguinMod. Add `scratch/pythonBridge.js` as an **unsandboxed** extension.

5. **Use it in your project.** Start with `set name to` (your project name), then `connect to python bridge`, then `run` or `result of`.

## Scratch blocks

All blocks are in English. Parameters and data can be added with the `+` and `−` buttons on `run` and `result of`.

| Block | What it does |
|---|---|
| `connect to python bridge` | Connects to the main app and runs the handshake. |
| `python bridge required for project [true/false]` | When `true` and not connected, the stage goes dark and a box explains that the bridge is required. Stage clicks and key presses are blocked until you connect. The **Python Bridge** link opens the project site. |
| `python bridge connected?` | True while the connection is up. |
| `disconnect from python bridge` | Closes the connection. If the project requires the bridge, the box appears again. |
| `set name to [name]` | Chooses the command folder for this project. Only `commands/<name>/` is searched. |
| `run [command]` | Runs a command and waits for it to finish. |
| `result of [command]` | Same as `run`, and reports the returned value. |
| `last python result` | The last result or error text. |
| `add command [command] with name [name]` | Asks you to approve, then creates `commands/<name>/<command>.py` with an empty `run` function. |

Timeouts: a command that runs longer than 10 seconds is stopped and reports `Timed out.`. The extension waits up to 15 seconds for a reply.

## Writing a command

Each command is one Python file with one `run` function:

```python
def run(parameters, data):
    return {"parameters": list(parameters), "data": list(data)}
```

- `parameters` and `data` are lists sent from Scratch.
- The return value should be JSON-friendly. Other values are converted to text.
- Only standard-library modules are guaranteed. Third-party packages must be installed for the Python that runs the main app.

A window example (it closes itself after 3 seconds, because commands have a 10-second limit):

```python
def run(parameters, data):
    import tkinter as tk
    root = tk.Tk()
    root.title("Python Bridge example")
    root.geometry("360x140")
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    text = "Parameters: %s\nData: %s" % (list(parameters), list(data))
    tk.Label(root, text=text, justify="left", padx=12, pady=12).pack(fill="both", expand=True)
    root.after(3000, root.destroy)
    root.mainloop()
    return "window shown"
```

## Command builder

Open `builder.html` in a browser. No server is needed.

- **New project:** enter the project name (the one used with `set name to`), a title and a description.
- **Load project (.config):** load an existing file and edit it.
- **+ Add command:** enter the command name and its Python code. Command names may only use letters, digits, `_` and `-`.
- **Export .config:** saves `<project name>.config`.

The builder checks the project before export: a valid name, a title, unique command names and non-empty code.

### `.config` format

```json
{
  "name": "starter",
  "title": "Starter",
  "description": "Example commands.",
  "commands": [
    {
      "name": "starter",
      "command": "ping",
      "python": "def run(parameters, data):\n    return 'pong'\n"
    }
  ]
}
```

## Main app (tray app)

Start it with `python pybridgeforpmod.py`. It has no window of its own. Its tray menu shows:

- **Python Bridge for Penguinmod:** opens the project site.
- **connected projects: N:** the number of connected projects.
- **Command history:** each run with its time, project name, command name and the script that ran.
- **Open Installer:** opens `installer.py` (or `installer.exe`) from the same folder.
- **Pause Bridge / Resume Bridge:** while paused, new connections are refused.
- **Exit:** closes the main app.

When a project adds a command, the main app shows a confirmation window with the file path. Nothing is written unless you click yes.

Errors are written to `bridge.log` next to `pybridgeforpmod.py`.

## Installer

Run the installer:

```bash
python installer.py
```

It opens a window with two choices:

- **Install from .config:** pick a `.config` file. The installer lists the `.config` files in its own folder first, or lets you browse. Review the commands, then click **Install this**. Each command is written to `commands/<name>/<command>.py`.
- **Remove installed commands:** pick a project, then select some or all of its commands and remove them. Removed commands are also removed from the approval list.

The install window also has a **Remove commands** button.

The installer finds the main app's folder by running `pybridgeforpmod --prefix`. If the main app is not on your PATH yet, the installer tells you to start it first.

## Security

- The main app listens on `127.0.0.1:8765` and rejects any other peer.
- Session keys come from ECDH P-256. Keys are derived with HKDF-SHA256 and combine both sides' random nonces.
- Messages are encrypted with AES-256-GCM. Each message has a counter, so replayed or reordered messages are rejected.
- A new key is made for every connection.

Known limit: the main app does not check the browser `Origin` header. Any web page open on your computer can start a handshake and send commands. Only keep the bridge running when you need it, and approve commands only from projects you trust.

## Troubleshooting

- **The stage goes dark:** the project needs the main app. Start `pybridgeforpmod.py`, then run `connect to python bridge`.
- **The tray icon says Paused:** choose **Resume Bridge**.
- **The installer says pybridgeforpmod was not found:** run `python pybridgeforpmod.py` once, open a new terminal, and try again.
- **A command shows `Timed out.`:** the script ran longer than 10 seconds.
- **The confirmation window for `add command` does not appear:** check `bridge.log`.
- **Scratch shows `Python Bridge is not running`:** the main app is not started, or another program uses port 8765.

## Project layout

```text
pybridgeforpmod.py       main app (tray app)
installer.py             installer (installs and removes commands)
builder.html             command builder (open in a browser)
requirements.txt         Python packages
scratch/pythonBridge.js  PenguinMod extension (load as unsandboxed)
examples/                sample .config and command
commands/                installed commands, created by the main app
  <project name>/
    <command>.py
    _allow.json          approved commands
bridge.log               errors, created only when something fails
```

## License

Add your license here.
