"""Interface Windows para o servidor Zebra IPP instalado separadamente."""

import ctypes
import ipaddress
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


MODULES = (
    "ipp_server.py", "zebra_formatter.py", "zebra_fast_engine.py", "print_pdf_zebra.py",
)
LEVELS = ("Todos", "Info", "Aviso", "Erro")
LOG_LIMIT = 5000
LEVEL_PATTERN = re.compile(r"\b(ERROR|CRITICAL|FATAL|WARNING|WARN|TRACEBACK)\b", re.I)


def server_command(python, ip, port, layout, printing, extras):
    address = str(ipaddress.IPv4Address(ip))
    if port not in {"631", "8631"}:
        raise ValueError("Escolha a porta 631 ou 8631.")
    if not layout or layout.startswith("-") or any(char.isspace() for char in layout):
        raise ValueError("Informe um valor válido para o modo de layout.")
    args = [python, "-u", "ipp_server.py", "--ip", address,
            "--port", port, "--layout-mode", layout]
    protected = ("--ip", "--port", "--layout-mode", "--print", "--spool-batch-labels")
    for arg in extras:
        option = arg.partition("=")[0]
        if option.startswith("-") and (
            option in {"-", "--"} or any(flag.startswith(option) for flag in protected)
        ):
            raise ValueError(f"Configure {option} pelos campos da interface.")
        args.append(arg)
    if printing:
        args.extend(("--print", "--spool-batch-labels", "1"))
    return args


def capture(process, events):
    with process.stdout as stream:
        for line in stream:
            events.put(("line", line.rstrip("\r\n")))
    events.put(("exit", process.wait()))


class Manager:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.history = deque(maxlen=LOG_LIMIT)
        self.process = None
        self.restart_args = None
        self.stopping = False
        self.closing = False
        self.probing = False
        self.folder = tk.StringVar(value=r"C:\ZebraIPP")
        self.python = tk.StringVar()
        self.ip = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="631")
        self.layout = tk.StringVar(value="smart")
        self.mode = tk.StringVar(value="Prévia")
        self.status = tk.StringVar(value="Parado")
        self.level = tk.StringVar(value=LEVELS[0])
        self.query = tk.StringVar()
        self.build_ui()
        self.set_controls()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(75, self.read_events)

    def build_ui(self):
        root = self.root
        root.title("Zebra IPP Manager")
        root.geometry("960x740")
        root.minsize(750, 620)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        settings = ttk.LabelFrame(frame, text="Servidor Zebra IPP", padding=10)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        for row, label, value, chooser in (
            (0, "Pasta do projeto", self.folder, filedialog.askdirectory),
            (1, "Python do projeto", self.python, filedialog.askopenfilename),
        ):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(settings, textvariable=value).grid(
                row=row, column=1, sticky="ew", padx=8, pady=3)
            ttk.Button(settings, text="Selecionar…", command=lambda v=value, c=chooser:
                       self.choose(v, c)).grid(row=row, column=2)
        fields = ttk.Frame(settings)
        fields.grid(row=2, column=0, columnspan=3, sticky="w", pady=7)
        for col, label, value, options, width in (
            (0, "IP (IPv4)", self.ip, (), 17),
            (1, "Porta", self.port, ("631", "8631"), 7),
            (2, "Modo", self.mode, ("Prévia", "Impressão"), 14),
            (3, "Modo de layout", self.layout, (), 15),
        ):
            ttk.Label(fields, text=label).grid(row=0, column=col, sticky="w", padx=(0, 10))
            widget = (ttk.Combobox(fields, textvariable=value, values=options,
                                   state="readonly", width=width) if options
                      else ttk.Entry(fields, textvariable=value, width=width))
            widget.grid(row=1, column=col, sticky="w", padx=(0, 10))
        ttk.Label(settings, text="Argumentos adicionais · um argumento por linha (ex.: --debug)").grid(
            row=3, column=0, columnspan=3, sticky="w")
        self.extras = tk.Text(settings, height=3, wrap="none", font="TkFixedFont")
        self.extras.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(3, 0))
        actions = ttk.Frame(frame, padding=(0, 9))
        actions.pack(fill="x")
        self.buttons = {}
        for label, action in (
            ("Iniciar", self.start), ("Interromper", self.stop),
            ("Reiniciar", self.restart), ("Opções do servidor", self.help_server),
            ("Testar TCP", self.test_port),
        ):
            button = ttk.Button(actions, text=label, command=action)
            button.pack(side="left", padx=(0, 5))
            self.buttons[label] = button
        ttk.Label(actions, textvariable=self.status).pack(side="right")
        logs = ttk.LabelFrame(frame, text="Eventos e diagnóstico", padding=10)
        logs.pack(fill="both", expand=True)
        filters = ttk.Frame(logs)
        filters.pack(fill="x", pady=(0, 7))
        ttk.Label(filters, text="Nível").pack(side="left")
        ttk.Combobox(filters, state="readonly", values=LEVELS, textvariable=self.level,
                     width=8).pack(side="left", padx=6)
        ttk.Label(filters, text="Buscar").pack(side="left", padx=(8, 0))
        ttk.Entry(filters, textvariable=self.query).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(filters, text="Exportar visão…", command=self.export).pack(side="right")
        scrollbar = ttk.Scrollbar(logs)
        scrollbar.pack(side="right", fill="y")
        self.console = tk.Text(logs, state="disabled", wrap="word", font="TkFixedFont",
                               bg="#111827", fg="#e5e7eb", yscrollcommand=scrollbar.set)
        self.console.pack(fill="both", expand=True)
        scrollbar.configure(command=self.console.yview)
        self.console.tag_configure("Erro", foreground="#fca5a5")
        self.console.tag_configure("Aviso", foreground="#fde68a")
        for variable in (self.level, self.query):
            variable.trace_add("write", self.redraw)

    def choose(self, variable, chooser):
        selection = chooser(parent=self.root)
        if selection:
            variable.set(selection)

    def project(self):
        folder = Path(self.folder.get().strip()).expanduser()
        if not self.folder.get().strip() or not folder.is_dir():
            raise ValueError("Selecione a pasta do projeto Zebra IPP.")
        folder = folder.resolve()
        missing = [name for name in MODULES if not (folder / name).is_file()]
        if missing:
            raise ValueError("Arquivos ausentes em " + str(folder) + "\n" + "\n".join(missing))
        chosen = self.python.get().strip()
        python = Path(chosen).expanduser() if chosen else folder / ".venv" / "Scripts" / "python.exe"
        if not python.is_file() or python.name.lower() != "python.exe":
            raise ValueError("Selecione o python.exe do ambiente usado pelo servidor.")
        return folder, str(python.resolve())

    def configuration(self):
        folder, python = self.project()
        extras = [line.strip() for line in self.extras.get("1.0", "end").splitlines() if line.strip()]
        command = server_command(python, self.ip.get().strip(), self.port.get(),
                                 self.layout.get().strip(), self.mode.get() == "Impressão", extras)
        return folder, command

    def launch(self, folder, command, diagnostic=False):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self.process = subprocess.Popen(
                command, cwd=folder, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.status.set("Falha ao iniciar")
            self.log(str(error), "Erro")
            return
        self.diagnostic = diagnostic
        self.status.set("Consultando opções" if diagnostic else "Processo ativo")
        self.log(subprocess.list2cmdline(command), "Info")
        self.set_controls()
        threading.Thread(target=capture, args=(self.process, self.events), daemon=True).start()

    def start(self):
        try:
            self.launch(*self.configuration())
        except ValueError as error:
            self.log(str(error), "Erro")
            messagebox.showerror("Configuração", str(error), parent=self.root)

    def stop(self):
        if self.process is None or self.stopping:
            return
        self.stopping = True
        self.status.set("Interrompendo…")
        self.set_controls()
        try:
            self.process.terminate()
        except OSError as error:
            if self.process.poll() is None:
                self.restart_args = None
                self.stopping = self.closing = False
                self.status.set("Falha ao interromper")
                self.log(str(error), "Erro")
                self.set_controls()

    def restart(self):
        try:
            self.restart_args = self.configuration()
        except ValueError as error:
            self.log(str(error), "Erro")
            messagebox.showerror("Configuração", str(error), parent=self.root)
            return
        self.stop()

    def help_server(self):
        try:
            folder, python = self.project()
            self.launch(folder, [python, "-u", "ipp_server.py", "--help"], diagnostic=True)
        except ValueError as error:
            self.log(str(error), "Erro")
            messagebox.showerror("Configuração", str(error), parent=self.root)

    def test_port(self):
        try:
            address = str(ipaddress.IPv4Address(self.ip.get().strip()))
            port = int(self.port.get())
        except ValueError as error:
            self.log(str(error), "Erro")
            return
        if address == "0.0.0.0":
            address = "127.0.0.1"
        self.probing = True
        self.set_controls()

        def probe():
            endpoint = f"{address}:{port}"
            try:
                with socket.create_connection((address, port), timeout=2):
                    result = (f"TCP {endpoint} respondeu.", "Info")
            except OSError as error:
                result = (f"TCP {endpoint} falhou: {error}", "Aviso")
            self.events.put(("probe", result))

        threading.Thread(target=probe, daemon=True).start()

    def set_controls(self):
        busy = self.process is not None
        self.buttons["Iniciar"].state(["disabled" if busy else "!disabled"])
        self.buttons["Opções do servidor"].state(["disabled" if busy else "!disabled"])
        self.buttons["Interromper"].state(["!disabled" if busy and not self.stopping else "disabled"])
        can_restart = busy and not self.stopping and not self.diagnostic
        self.buttons["Reiniciar"].state(["!disabled" if can_restart else "disabled"])
        self.buttons["Testar TCP"].state(["disabled" if self.probing else "!disabled"])

    def read_events(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                match = LEVEL_PATTERN.search(value)
                level = "Info"
                if match:
                    level = "Aviso" if match[0].upper().startswith("WARN") else "Erro"
                self.log(value, level)
            elif kind == "probe":
                self.probing = False
                self.log(*value)
                self.set_controls()
            else:
                requested_stop = self.stopping
                self.process = None
                self.stopping = False
                failed = value != 0 and not requested_stop
                self.status.set("Falha no processo" if failed else "Parado")
                self.log(f"Processo encerrado (código {value}).", "Erro" if failed else "Info")
                self.set_controls()
                if self.closing:
                    self.root.destroy()
                    return
                if self.restart_args is not None:
                    args, self.restart_args = self.restart_args, None
                    self.launch(*args)
        self.root.after(75, self.read_events)

    def matches(self, line, level):
        return (self.level.get() in ("Todos", level)
                and self.query.get().casefold() in line.casefold())

    def log(self, message, level):
        for part in message.splitlines() or [""]:
            time = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
            line = f"{time}  [{level}]  {part}\n"
            dropped_visible = len(self.history) == LOG_LIMIT and self.matches(*self.history[0])
            self.history.append((line, level))
            if dropped_visible or self.matches(line, level):
                self.console.configure(state="normal")
                if dropped_visible:
                    self.console.delete("1.0", "2.0")
                if self.matches(line, level):
                    follow = self.console.yview()[1] >= 0.999
                    self.console.insert("end", line, level)
                    if follow:
                        self.console.see("end")
                self.console.configure(state="disabled")

    def redraw(self, *_):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        for line, level in self.history:
            if self.matches(line, level):
                self.console.insert("end", line, level)
        self.console.see("end")
        self.console.configure(state="disabled")

    def export(self):
        name = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt",
                                            filetypes=[("Texto", "*.txt")])
        if name:
            try:
                Path(name).write_text("".join(line for line, level in self.history
                                              if self.matches(line, level)), encoding="utf-8")
            except OSError as error:
                messagebox.showerror("Exportação", str(error), parent=self.root)

    def close(self):
        self.restart_args = None
        if self.process is None:
            self.root.destroy()
        else:
            self.closing = True
            self.stop()


def main():
    root = tk.Tk()
    if os.name == "nt" and getattr(sys, "frozen", False):
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    Manager(root)
    root.mainloop()


if __name__ == "__main__":
    main()
