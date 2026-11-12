#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificador somente-leitura da rede e do servidor Zebra IPP no Windows.

Exemplos:
  py verificador_zebra.py --ip 192.168.10.76 --port 631
  py verificador_zebra.py --gui
  py verificador_zebra.py --ip 192.168.10.76 --port 8631 --json

NUNCA envia Print-Job, ZPL, reinicia servicos ou altera o firewall.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import platform
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Callable

DEFAULT_IP = "192.168.10.76"
DEFAULT_PORT = 631
DEFAULT_PATH = "/ipp/print"
PRINTER_NAME = "ZDesigner ZD220-203dpi ZPL"


@dataclass
class Check:
    name: str
    status: str              # OK, AVISO, ERRO, INFO
    detail: str
    hint: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _val(tag: int, name: str, raw: bytes) -> bytes:
    bname = name.encode("utf-8")
    return struct.pack(">BH", tag, len(bname)) + bname + struct.pack(">H", len(raw)) + raw


def build_ipp_get_attrs(ip: str, port: int, path: str, request_id: int = 127) -> bytes:
    uri = f"ipp://{ip}:{port}{path}"
    result = bytearray(b"\x02\x00" + struct.pack(">HI", 0x000B, request_id))
    result.append(0x01)  # operation-attributes-tag
    result += _val(0x47, "attributes-charset", b"utf-8")
    result += _val(0x48, "attributes-natural-language", b"en")
    result += _val(0x45, "printer-uri", uri.encode("utf-8"))
    for i, attribute in enumerate((
        "printer-name", "printer-state", "printer-uri-supported",
        "document-format-supported", "operations-supported", "media-supported",
    )):
        result += _val(0x44, "requested-attributes" if i == 0 else "", attribute.encode("utf-8"))
    result.append(0x03)  # end-of-attributes-tag
    return bytes(result)


def parse_ipp_response(body: bytes, expected_request_id: int) -> dict[str, Any]:
    if len(body) < 9:
        raise ValueError("Resposta IPP incompleta (menos de 9 bytes)")
    version = f"{body[0]}.{body[1]}"
    status, reqid = struct.unpack_from(">HI", body, 2)
    if reqid != expected_request_id:
        raise ValueError(f"Request-ID divergente: enviado={expected_request_id}, resposta={reqid}")
    offset = 8
    current_group = None
    last_name = None
    attrs: dict[str, list[Any]] = {}
    while offset < len(body):
        tag = body[offset]
        offset += 1
        if tag == 0x03:
            return {"version": version, "status": status, "request_id": reqid, "attributes": attrs}
        if tag <= 0x0F:
            current_group = tag
            last_name = None
            continue
        if offset + 2 > len(body):
            raise ValueError("Atributo IPP truncado (nome)")
        nlen = struct.unpack_from(">H", body, offset)[0]
        offset += 2
        if offset + nlen + 2 > len(body):
            raise ValueError("Atributo IPP com nome truncado")
        name = body[offset:offset+nlen].decode("utf-8", "replace")
        offset += nlen
        vlen = struct.unpack_from(">H", body, offset)[0]
        offset += 2
        if offset + vlen > len(body):
            raise ValueError("Atributo IPP com valor truncado")
        raw = body[offset:offset+vlen]
        offset += vlen
        if name:
            last_name = name
        if current_group != 0x04 or not last_name:
            continue
        if tag in (0x21, 0x23) and len(raw) == 4:
            value: Any = struct.unpack(">i", raw)[0]
        elif tag == 0x22 and len(raw) == 1:
            value = bool(raw[0])
        elif tag in (0x32, 0x33, 0x34, 0x37):
            # Collections/resolutions are not needed to verify the endpoint.
            continue
        else:
            value = raw.decode("utf-8", "replace")
        attrs.setdefault(last_name, []).append(value)
    raise ValueError("Resposta IPP sem marcador end-of-attributes (0x03)")


def check_tcp(host: str, port: int, timeout: float = 2.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "Conexão TCP aceita"
    except (socket.timeout, OSError) as exc:
        return False, f"Não foi possível conectar: {exc}"


def check_http(host: str, port: int, timeout: float = 2.5) -> tuple[bool, str, dict[str, Any]]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/", headers={"User-Agent": "ZebraIPP-Verificador/1.0"})
        res = conn.getresponse()
        payload = res.read(1024).decode("utf-8", "replace").strip()
        return res.status == 200, f"HTTP {res.status}: {payload[:170] or '(sem corpo)'}", {"http_status": res.status}
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return False, f"Falha HTTP: {type(exc).__name__}: {exc}", {}
    finally:
        conn.close()


def check_ipp(host: str, port: int, path: str, timeout: float = 3.5) -> tuple[bool, str, dict[str, Any]]:
    payload = build_ipp_get_attrs(host, port, path)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("POST", path, body=payload, headers={
            "Content-Type": "application/ipp", "Accept": "application/ipp",
            "User-Agent": "ZebraIPP-Verificador/1.0",
        })
        res = conn.getresponse()
        response_body = res.read(256 * 1024)
        content_type = res.getheader("Content-Type", "")
        if res.status != 200:
            return False, f"HTTP {res.status}, esperado 200", {"http_status": res.status}
        if "application/ipp" not in content_type.lower():
            return False, f"Content-Type inesperado: {content_type!r}", {"content_type": content_type}
        parsed = parse_ipp_response(response_body, 127)
        if parsed["status"] != 0:
            return False, f"IPP respondeu erro 0x{parsed['status']:04X}", parsed
        attrs = parsed["attributes"]
        if not attrs:
            return False, "IPP 0x0000, mas nenhum atributo de impressora retornado", parsed
        printer = (attrs.get("printer-name") or ["(nome não informado)"])[0]
        docs = ", ".join(str(x) for x in attrs.get("document-format-supported", []))
        summary = f"IPP {parsed['version']} OK; impressora={printer}; formatos={docs or '(não enviados)'}"
        return True, summary, parsed
    except (OSError, http.client.HTTPException, ValueError, struct.error) as exc:
        return False, f"Falha IPP: {type(exc).__name__}: {exc}", {}
    finally:
        conn.close()


def check_mdns(ip: str, port: int, path: str, seconds: float = 3.0) -> tuple[str, str, dict[str, Any]]:
    if importlib.util.find_spec("zeroconf") is None:
        return "AVISO", "Biblioteca zeroconf ausente; descoberta DNS-SD não verificada", {}
    from zeroconf import ServiceBrowser, Zeroconf

    entries: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()

    class Listener:
        def add_service(self, zc, service_type, name):
            self.update_service(zc, service_type, name)

        def update_service(self, zc, service_type, name):
            service = zc.get_service_info(service_type, name, timeout=1200)
            if not service:
                return
            record = {
                "name": name, "addresses": service.parsed_addresses(),
                "port": service.port,
                "txt": {k.decode("utf-8", "replace"): v.decode("utf-8", "replace")
                        for k, v in service.properties.items()},
            }
            with lock:
                entries[name] = record

        def remove_service(self, zc, service_type, name):
            pass

    zc = Zeroconf()
    browser = None
    try:
        browser = ServiceBrowser(zc, "_ipp._tcp.local.", Listener())
        time.sleep(max(0.5, seconds))
        with lock:
            found = list(entries.values())
        matching = [x for x in found if ip in x["addresses"]]
        exact = [x for x in matching if x["port"] == port and
                 x["txt"].get("rp", "").strip("/") == path.strip("/")]
        if exact:
            s = exact[0]
            return "OK", f"DNS-SD encontrado: {s['name']} ({ip}:{port}, rp={s['txt'].get('rp')})", {"found": found, "matched": s}
        if matching:
            shown = "; ".join(f"{x['name']} porta={x['port']} rp={x['txt'].get('rp')}" for x in matching)
            return "AVISO", f"mDNS encontrado para {ip}, mas porta/caminho diferem: {shown}", {"found": found}
        if found:
            shown = "; ".join(f"{x['name']} {','.join(x['addresses'])}:{x['port']}" for x in found[:5])
            return "AVISO", f"Há impressoras IPP anunciadas, mas nenhuma no IP {ip}. Encontradas: {shown}", {"found": found}
        return "AVISO", "Nenhum serviço _ipp._tcp visto neste Windows durante a busca", {"found": []}
    except Exception as exc:
        return "AVISO", f"Não foi possível consultar mDNS: {type(exc).__name__}: {exc}", {}
    finally:
        if browser is not None:
            browser.cancel()
        zc.close()


def powershell(command: str, timeout: float = 9.0) -> tuple[Any | None, str | None]:
    if os.name != "nt":
        return None, "Disponível apenas no Windows"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference='Stop'; " + command + " | ConvertTo-Json -Compress -Depth 5"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode:
            return None, (proc.stderr or proc.stdout).strip()[:400]
        out = proc.stdout.strip()
        return (json.loads(out) if out else []), None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return None, f"PowerShell: {exc}"


def _as_list(obj: Any) -> list[Any]:
    return obj if isinstance(obj, list) else ([] if obj is None else [obj])


def inspect_windows(ip: str, port: int, printer_name: str) -> list[Check]:
    checks: list[Check] = []
    if os.name != "nt":
        return [Check("Windows e impressora USB", "INFO", "Diagnóstico Windows ignorado fora do Windows")]

    profiles, e = powershell("Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory,IPv4Connectivity")
    if e:
        checks.append(Check("Perfil da rede Windows", "AVISO", e))
    else:
        rows = _as_list(profiles)
        pr = ", ".join(f"{r.get('InterfaceAlias')}: {r.get('NetworkCategory')}" for r in rows if isinstance(r, dict))
        checks.append(Check("Perfil da rede Windows", "OK" if any(r.get("NetworkCategory") == "Private" for r in rows if isinstance(r, dict)) else "AVISO", pr or "Perfil não disponível", "A rede usada pela Zebra deve ser confiável; perfil público pode restringir conexões."))

    # Numeric port validated before insertion into PowerShell string.
    sockets, e = powershell(f"Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess")
    if e:
        checks.append(Check("Processo escutando na porta IPP", "AVISO", e))
    else:
        rows = _as_list(sockets)
        if rows:
            processes = ", ".join(f"PID {r.get('OwningProcess')} ({r.get('LocalAddress')}:{r.get('LocalPort')})" for r in rows if isinstance(r, dict))
            checks.append(Check("Processo escutando na porta IPP", "OK", processes))
        else:
            checks.append(Check("Processo escutando na porta IPP", "ERRO", f"Nenhum processo LISTENING na porta {port}", "Inicie o servidor com --port correspondente."))

    printer_filter = printer_name.replace("'", "''")
    printer, e = powershell(f"Get-Printer -Name '{printer_filter}' -ErrorAction Stop | Select-Object Name,PrinterStatus,PortName,DriverName,Shared")
    if e:
        checks.append(Check("Fila Zebra do Windows", "AVISO", e, "Confira o nome exato em Configurações > Impressoras e scanners; isso não interfere na descoberta IPP."))
    else:
        rows = _as_list(printer)
        if rows and isinstance(rows[0], dict):
            x = rows[0]
            checks.append(Check("Fila Zebra do Windows", "OK", f"{x.get('Name')} | status={x.get('PrinterStatus')} | porta={x.get('PortName')} | driver={x.get('DriverName')}", "O status do spooler não confirma uma impressão física."))
        else:
            checks.append(Check("Fila Zebra do Windows", "AVISO", "Fila não encontrada"))

    # Review rules without creating/changing any firewall configuration.
    rules, e = powershell("Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow | Where-Object { $_.DisplayName -like '*Zebra*' -or $_.DisplayName -like '*mDNS*' } | Select-Object DisplayName,Profile")
    if e:
        checks.append(Check("Regras de firewall (leitura)", "AVISO", e))
    else:
        rlist = _as_list(rules)
        labels = sorted(set(str(r.get("DisplayName")) for r in rlist if isinstance(r, dict)))
        checks.append(Check("Regras de firewall (leitura)", "INFO", ", ".join(labels[:12]) or "Nenhuma regra Zebra/mDNS com esse nome", "Listagem indicativa: regras habilitadas não comprovam que multicast chega ao Android."))
    return checks


def inspect_modules() -> Check:
    modules = {"zeroconf": "zeroconf", "Pillow": "PIL", "PyMuPDF": "pymupdf", "pywin32": "win32print"}
    present = [name for name, mod in modules.items() if importlib.util.find_spec(mod) is not None]
    absent = [name for name in modules if name not in present]
    # Dependencies are not needed for testing TCP, HTTP, or IPP.
    return Check("Dependências Python", "OK" if not absent else "AVISO",
                 "Instalados: " + (", ".join(present) or "nenhum") + "; ausentes: " + (", ".join(absent) or "nenhum"),
                 "Os testes básicos de TCP/HTTP/IPP não exigem dependências externas.", {"installed": present, "missing": absent})


def run_checks(ip: str, port: int, path: str = DEFAULT_PATH,
               printer_name: str = PRINTER_NAME, timeout: float = 2.5,
               mdns_seconds: float = 2.0, windows: bool = True,
               mdns: bool = True, on_check: Callable[[Check], None] | None = None) -> dict[str, Any]:
    checks: list[Check] = []
    def emit(c: Check):
        checks.append(c)
        if on_check:
            on_check(c)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    emit(Check("Ambiente", "INFO", f"{platform.system()} {platform.release()} | Python {platform.python_version()} | diagnóstico somente-leitura"))
    emit(inspect_modules())

    active_ok = False
    for candidate in sorted(set((631, 8631, port))):
        yes, detail = check_tcp(ip, candidate, timeout=timeout)
        is_active = candidate == port
        status = ("OK" if yes else "ERRO") if is_active else "INFO"
        hint = "Confira --port e se o servidor está aberto." if is_active and not yes else "Porta alternativa, não é obrigatório estar aberta."
        emit(Check(f"TCP {ip}:{candidate}" + (" (configurada)" if is_active else " (alternativa)"), status, detail, hint, {"port": candidate, "open": yes}))
        if is_active:
            active_ok = yes

    # RAW 9100 is not used by this project; a closed port is normal.
    raw, msg = check_tcp(ip, 9100, timeout=min(timeout, 1.0))
    emit(Check("RAW TCP 9100 (opcional)", "INFO", "Aberta" if raw else "Fechada — normal para esta ponte IPP", "9100 é RAW/ZPL e não substitui IPP.", {"open": raw}))
    emit(Check("Multicast UDP 5353", "INFO", "A porta 5353 é UDP/multicast: o teste TCP não se aplica.", "A validação funcional do DNS-SD está no próximo teste."))

    if active_ok:
        ok, detail, data = check_http(ip, port, timeout=timeout)
        emit(Check("HTTP GET /", "OK" if ok else "ERRO", detail, "No Android, abra o mesmo URL: http://IP:PORTA/", data))
        ok, detail, data = check_ipp(ip, port, path, timeout=max(3.0, timeout))
        emit(Check("IPP Get-Printer-Attributes", "OK" if ok else "ERRO", detail, "Este teste é somente consulta; nunca envia uma etiqueta.", data))
    else:
        emit(Check("HTTP GET /", "AVISO", "Ignorado: porta configurada inacessível"))
        emit(Check("IPP Get-Printer-Attributes", "AVISO", "Ignorado: porta configurada inacessível"))

    if mdns:
        status, detail, data = check_mdns(ip, port, path, seconds=mdns_seconds)
        emit(Check("DNS-SD _ipp._tcp", status, detail,
                   "Um resultado OK no próprio Windows NÃO garante descoberta no tablet; valide com navegador mDNS no Android.", data))
    else:
        emit(Check("DNS-SD _ipp._tcp", "INFO", "Ignorado por --no-mdns"))

    if windows:
        for c in inspect_windows(ip, port, printer_name):
            emit(c)

    # The endpoint IP may be on another computer: no implications about Android from Windows checks.
    emit(Check("Limitação do teste", "INFO", "Realizado neste computador; não consegue verificar diretamente o cache ou o serviço de impressão do Android.", "Se o mDNS aparece no tablet mas não há op=0x000B, investigue o serviço de impressão no tablet."))
    overall = "ERRO" if any(c.status == "ERRO" for c in checks) else ("AVISO" if any(c.status == "AVISO" for c in checks) else "OK")
    return {"app": "Verificador Zebra IPP", "version": "1.0.0", "timestamp": now,
            "endpoint": f"ipp://{ip}:{port}{path}", "overall": overall,
            "checks": [asdict(c) for c in checks]}


def render_text(report: dict[str, Any]) -> str:
    rows = ["=" * 68, "VERIFICADOR ZEBRA IPP - CONEXAO E PORTAS",
            "=" * 68, f"Data: {report['timestamp']}",
            f"Servidor: {report['endpoint']}", f"Resultado geral: {report['overall']}", ""]
    for c in report["checks"]:
        rows.append(f"[{c['status']}] {c['name']}: {c['detail']}")
        if c.get("hint") and c["status"] != "OK":
            rows.append("     Dica: " + c["hint"])
    rows += ["", "Este programa NÃO envia trabalhos de impressão nem muda firewall/serviços.",
             "mDNS descoberto no Windows não prova descoberta no Android."]
    return "\n".join(rows) + "\n"


def save_report(report: dict[str, Any], folder: str | Path) -> tuple[Path, Path]:
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    txt = path / f"diagnostico_zebra_{suffix}.txt"
    js = path / f"diagnostico_zebra_{suffix}.json"
    txt.write_text(render_text(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return txt, js


def start_gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise SystemExit(f"Tkinter indisponível neste Python: {exc}")

    root = tk.Tk()
    root.title("Zebra IPP | Verificador de Conexão e Portas")
    root.geometry("900x630")
    root.minsize(720, 510)
    bg = "#f3f6fa"
    root.configure(bg=bg)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"), background=bg, foreground="#13233e")
    style.configure("TButton", font=("Segoe UI", 10), padding=7)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Zebra IPP | Diagnóstico de Conexão", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Testes de rede e impressora • Somente leitura • Sem impressão física").pack(anchor="w", pady=(4, 14))

    config = ttk.Frame(frame)
    config.pack(fill="x")
    ipvar = tk.StringVar(value=DEFAULT_IP)
    portvar = tk.StringVar(value=str(DEFAULT_PORT))
    printervar = tk.StringVar(value=PRINTER_NAME)
    for label, var, width in (("IP do Windows", ipvar, 19), ("Porta IPP", portvar, 9), ("Fila da Zebra", printervar, 34)):
        sub = ttk.Frame(config)
        sub.pack(side="left", padx=(0, 15))
        ttk.Label(sub, text=label).pack(anchor="w")
        ttk.Entry(sub, textvariable=var, width=width).pack(anchor="w", pady=(4, 0))

    toolbar = ttk.Frame(frame)
    toolbar.pack(fill="x", pady=(16, 10))
    result = {"value": None}
    status_var = tk.StringVar(value="Pronto para testar")

    log = tk.Text(frame, height=20, wrap="word", font=("Consolas", 10), padx=12, pady=10,
                  background="#101827", foreground="#e4edf7", insertbackground="#e4edf7",
                  highlightthickness=0, borderwidth=0)
    log.pack(fill="both", expand=True)
    log.tag_configure("OK", foreground="#6fe3af")
    log.tag_configure("ERRO", foreground="#ff8585")
    log.tag_configure("AVISO", foreground="#f4c66d")
    log.tag_configure("INFO", foreground="#b9d1ef")

    def append(c: Check):
        def update():
            log.insert("end", f"[{c.status}] {c.name}\n", c.status)
            log.insert("end", f"    {c.detail}\n")
            if c.hint and c.status != "OK":
                log.insert("end", f"    Dica: {c.hint}\n")
            log.see("end")
        root.after(0, update)

    def run():
        try:
            ip = str(ipaddress.ip_address(ipvar.get().strip()))
            if ":" in ip:
                raise ValueError("Informe um endereço IPv4")
            port = int(portvar.get())
            if port < 1 or port > 65535:
                raise ValueError("A porta deve estar entre 1 e 65535")
        except ValueError as exc:
            messagebox.showerror("Dados inválidos", str(exc))
            return
        btn.configure(state="disabled")
        export.configure(state="disabled")
        log.delete("1.0", "end")
        status_var.set("Executando testes...")
        result["value"] = None

        def task():
            try:
                report = run_checks(ip, port, printer_name=printervar.get().strip(), on_check=append)
                def done():
                    result["value"] = report
                    status_var.set("Concluído: " + report["overall"])
                    export.configure(state="normal")
                    btn.configure(state="normal")
                root.after(0, done)
            except Exception as exc:
                msg = str(exc)
                def failed():
                    status_var.set(f"Erro: {msg}")
                    btn.configure(state="normal")
                root.after(0, failed)
        threading.Thread(target=task, daemon=True).start()

    def save():
        if result["value"] is None:
            return
        folder = filedialog.askdirectory(title="Escolha onde salvar o diagnóstico")
        if folder:
            try:
                txt, js = save_report(result["value"], folder)
                messagebox.showinfo("Relatório salvo", f"TXT: {txt}\nJSON: {js}")
            except OSError as exc:
                messagebox.showerror("Não foi possível salvar", str(exc))

    btn = ttk.Button(toolbar, text="Verificar conexão e portas", command=run)
    btn.pack(side="left")
    export = ttk.Button(toolbar, text="Salvar relatório", command=save, state="disabled")
    export.pack(side="left", padx=(10, 0))
    ttk.Label(toolbar, textvariable=status_var).pack(side="right")
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diagnostica Zebra IPP sem enviar impressão")
    p.add_argument("--gui", action="store_true", help="Abre interface gráfica (Tkinter)")
    p.add_argument("--ip", default=DEFAULT_IP, help="IPv4 do Windows que anuncia o IPP")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Porta IPP (padrão: 631)")
    p.add_argument("--path", default=DEFAULT_PATH, help="Caminho IPP (padrão: /ipp/print)")
    p.add_argument("--printer", default=PRINTER_NAME, help="Nome da fila Zebra no Windows")
    p.add_argument("--timeout", type=float, default=2.5)
    p.add_argument("--no-mdns", action="store_true", help="Não consultar mDNS")
    p.add_argument("--no-windows", action="store_true", help="Não consultar PowerShell/Windows")
    p.add_argument("--output", default=None, help="Pasta para salvar TXT e JSON")
    p.add_argument("--json", action="store_true", help="Imprime relatório JSON no console")
    args = p.parse_args(argv)
    if args.gui:
        start_gui()
        return 0
    if not (1 <= args.port <= 65535):
        p.error("Porta inválida (1 a 65535)")
    if not args.path.startswith("/"):
        p.error("O caminho IPP deve começar com /")
    try:
        ipaddress.IPv4Address(args.ip)
    except ipaddress.AddressValueError:
        p.error("Forneça um endereço IPv4 válido")
    report = run_checks(args.ip, args.port, args.path, args.printer,
                        args.timeout, windows=not args.no_windows,
                        mdns=not args.no_mdns)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    if args.output:
        txt, js = save_report(report, args.output)
        if not args.json:
            print(f"Relatórios salvos: {txt} | {js}")
    return 1 if report["overall"] == "ERRO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
