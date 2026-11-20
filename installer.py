# Python Bridge installer.
# Installs and removes commands in the pybridgeforpmod commands folder.
# Install: pick a .config made by the command builder.
# Remove: pick a project name, then remove all or some of its commands.

import glob
import json
import os
import subprocess
import sys


def app_dir():
    """The folder the installer runs from (the exe folder when frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def find_configs(folder):
    return sorted(glob.glob(os.path.join(folder, "*.config")))


def find_root():
    """Ask pybridgeforpmod where it is installed. Fall back to the Windows user PATH."""
    try:
        out = subprocess.check_output(["pybridgeforpmod", "--prefix"], universal_newlines=True, timeout=10)
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        if lines and os.path.isdir(lines[-1]):
            return lines[-1]
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            path, _ = winreg.QueryValueEx(key, "Path")
            for part in path.split(";"):
                if part and os.path.isfile(os.path.join(part, "pybridgeforpmod.py")):
                    return part
        except Exception:
            pass
    return ""


def safe(text):
    keep = "".join(ch for ch in str(text or "") if ch.isalnum() or ch in "_-")
    if not keep:
        raise ValueError("invalid name: %r" % (text,))
    return keep[:64]


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
        raise ValueError("This file has no commands list.")
    return data


def install_commands(config, root):
    """Write every command as commands/<name>/<command>.py under root. Returns the commands folder."""
    dest_root = os.path.join(root, "commands")
    for item in config["commands"]:
        folder = os.path.join(dest_root, safe(item.get("name") or config.get("name")))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe(item.get("command")) + ".py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(item.get("python") or "")
    return dest_root


def list_projects(root):
    """Project folders under commands/ that hold at least one command."""
    base = os.path.join(root, "commands")
    if not os.path.isdir(base):
        return []
    return sorted(name for name in os.listdir(base)
                  if os.path.isdir(os.path.join(base, name)) and list_commands(root, name))


def list_commands(root, name):
    folder = os.path.join(root, "commands", safe(name))
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(folder, "*.py")))


def remove_commands(root, name, commands):
    """Delete the given commands of one project. Drops their approvals and the folder when empty."""
    folder = os.path.join(root, "commands", safe(name))
    removed = []
    for command in commands:
        path = os.path.join(folder, safe(command) + ".py")
        if os.path.isfile(path):
            os.remove(path)
            removed.append(command)
    allow_path = os.path.join(folder, "_allow.json")
    if os.path.isfile(allow_path):
        try:
            with open(allow_path, "r", encoding="utf-8") as handle:
                allowed = json.load(handle).get("commands", [])
        except Exception:
            allowed = []
        allowed = [c for c in allowed if c not in removed]
        if allowed:
            with open(allow_path, "w", encoding="utf-8") as handle:
                json.dump({"commands": allowed}, handle, indent=2)
        else:
            os.remove(allow_path)
    if os.path.isdir(folder) and not list_commands(root, name):
        for leftover in glob.glob(os.path.join(folder, "*")):
            if os.path.isfile(leftover):
                os.remove(leftover)
        os.rmdir(folder)
    return removed


def choose_config(tk, filedialog, hidden):
    """Ask which .config to install. Lists the .config files in the install folder if any."""
    found = find_configs(app_dir())
    if not found:
        return filedialog.askopenfilename(
            title="Choose a .config file",
            filetypes=[("Config files", "*.config *.json"), ("All files", "*.*")],
        )
    result = {"path": None}
    win = tk.Toplevel(hidden)
    win.title("Python Bridge")
    win.geometry("420x300")
    tk.Label(win, text="Which .config do you want to install?", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
    listing = tk.Listbox(win)
    listing.pack(fill="both", expand=True, padx=12)
    for path in found:
        listing.insert("end", os.path.basename(path))
    listing.selection_set(0)

    def pick(_event=None):
        chosen = listing.curselection()
        if chosen:
            result["path"] = found[chosen[0]]
        win.destroy()

    def browse():
        result["path"] = filedialog.askopenfilename(
            title="Choose a .config file",
            filetypes=[("Config files", "*.config *.json"), ("All files", "*.*")],
            parent=win,
        ) or None
        win.destroy()

    row = tk.Frame(win)
    row.pack(fill="x", padx=12, pady=12)
    tk.Button(row, text="Browse...", command=browse).pack(side="left")
    tk.Button(row, text="Cancel", command=win.destroy).pack(side="right")
    tk.Button(row, text="Install this", command=pick).pack(side="right", padx=(0, 8))
    listing.bind("<Double-Button-1>", pick)
    win.grab_set()
    win.wait_window()
    return result["path"]


def remove_dialog(tk, messagebox, root):
    base = find_root()
    if not base:
        messagebox.showerror("Python Bridge", "pybridgeforpmod was not found. Run pybridgeforpmod once, then try again.")
        return
    if not list_projects(base):
        messagebox.showinfo("Python Bridge", "No installed commands were found.")
        return

    win = tk.Toplevel(root)
    win.title("Remove commands")
    win.geometry("440x480")
    win.minsize(360, 360)
    tk.Label(win, text="Project name", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 4))

    project_var = tk.StringVar(win)
    projects = list_projects(base)
    project_var.set(projects[0])
    picker = tk.OptionMenu(win, project_var, *projects)
    picker.pack(anchor="w", padx=12)

    body = tk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=8)
    checks = {}

    def refresh_commands(*_):
        for child in body.winfo_children():
            child.destroy()
        checks.clear()
        for command in list_commands(base, project_var.get()):
            var = tk.BooleanVar(win, value=False)
            tk.Checkbutton(body, text=command, variable=var, anchor="w").pack(fill="x", anchor="w")
            checks[command] = var

    def refresh_projects():
        names = list_projects(base)
        menu = picker["menu"]
        menu.delete(0, "end")
        for name in names:
            menu.add_command(label=name, command=lambda value=name: project_var.set(value))
        if not names:
            win.destroy()
            return False
        if project_var.get() not in names:
            project_var.set(names[0])
        return True

    project_var.trace_add("write", refresh_commands)
    refresh_commands()

    def select_all():
        everything_on = bool(checks) and all(var.get() for var in checks.values())
        for var in checks.values():
            var.set(not everything_on)

    def remove_selected():
        picked = [command for command, var in checks.items() if var.get()]
        if not picked:
            messagebox.showinfo("Remove commands", "Select at least one command.")
            return
        text = "Remove %d command(s) from %s?\n\n%s" % (len(picked), project_var.get(), "\n".join(picked))
        if not messagebox.askyesno("Remove commands", text):
            return
        try:
            removed = remove_commands(base, project_var.get(), picked)
        except Exception as error:
            messagebox.showerror("Remove commands", "Could not remove: " + str(error))
            return
        messagebox.showinfo("Remove commands", "Removed: %d" % len(removed))
        if refresh_projects():
            refresh_commands()

    row = tk.Frame(win)
    row.pack(fill="x", padx=12, pady=(0, 12))
    tk.Button(row, text="Select all", command=select_all).pack(side="left")
    tk.Button(row, text="Remove selected", command=remove_selected).pack(side="right")
    tk.Button(row, text="Close", command=win.destroy).pack(side="right", padx=(0, 8))


def show_install(tk, messagebox, parent, config):
    """The install window for one loaded config. Keeps a Remove commands button too."""
    title = config.get("title") or "Untitled"
    commands = config["commands"]

    win = tk.Toplevel(parent)
    win.title("Set Up Commands For %s" % title)
    win.geometry("640x520")
    win.minsize(480, 420)
    tk.Label(win, text="Set Up Commands For %s" % title, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
    tk.Label(win, text="Description: %s" % (config.get("description") or ""), wraplength=600, justify="left").pack(anchor="w", padx=12)
    box = tk.Listbox(win)
    box.pack(fill="x", padx=12, pady=8)
    for item in commands:
        box.insert("end", "%s / %s" % (item.get("name") or config.get("name"), item.get("command")))

    # Bottom bar first, so the buttons stay visible when the window is resized.
    bottom = tk.Frame(win)
    bottom.pack(side="bottom", fill="x", padx=12, pady=10)

    code = tk.Text(win, height=14, wrap="none")
    code.pack(fill="both", expand=True, padx=12)

    def show(_event=None):
        picked = box.curselection()
        if not picked:
            return
        code.config(state="normal")
        code.delete("1.0", "end")
        code.insert("1.0", commands[picked[0]].get("python") or "")
        code.config(state="disabled")  # preview only, not editable

    box.bind("<<ListboxSelect>>", show)
    if commands:
        box.selection_set(0)
        show()

    def install():
        if not messagebox.askyesno("Install commands", "Are you sure you want to install these commands?"):
            return
        folder = find_root()
        if not folder:
            messagebox.showerror(
                "Python Bridge",
                "pybridgeforpmod was not found. Run pybridgeforpmod once so it can add itself to PATH, then run this installer again.",
            )
            return
        try:
            dest = install_commands(config, folder)
        except Exception as error:
            messagebox.showerror("Python Bridge", "Install failed: " + str(error))
            return
        messagebox.showinfo("Python Bridge", "Installed into " + dest)

    tk.Button(bottom, text="Install", command=install, width=14).pack(side="right")
    tk.Button(bottom, text="Remove commands", command=lambda: remove_dialog(tk, messagebox, win), width=16).pack(side="left")


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("Python Bridge")
    root.geometry("360x180")
    tk.Label(root, text="What do you want to do?", font=("Segoe UI", 12, "bold")).pack(pady=(18, 12))

    def install_flow():
        path = choose_config(tk, filedialog, root)
        if not path:
            return
        try:
            config = load_config(path)
        except Exception as error:
            messagebox.showerror("Python Bridge", "Could not read the config: " + str(error))
            return
        show_install(tk, messagebox, root, config)

    tk.Button(root, text="Install from .config", command=install_flow, width=28).pack(pady=6)
    tk.Button(root, text="Remove installed commands", command=lambda: remove_dialog(tk, messagebox, root), width=28).pack(pady=6)
    root.mainloop()


if __name__ == "__main__":
    main()
