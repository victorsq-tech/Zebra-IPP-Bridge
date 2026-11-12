"""Verifica conexões TCP a partir do computador que executa este script."""

import argparse
import socket


def tcp_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("use uma porta de 1 a 65535")
    return port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", default="127.0.0.1", help="Endereço do servidor")
    parser.add_argument("--port", type=tcp_port, action="append",
                        help="Porta TCP (repita para testar várias). Padrão: 631 e 8631.")
    args = parser.parse_args()

    failed = False
    for port in args.port or [631, 8631]:
        target = f"{args.ip}:{port}"
        try:
            with socket.create_connection((args.ip, port), timeout=3):
                print(f"OK {target} aceita conexão TCP")
        except OSError as error:
            print(f"ERRO {target}: {error}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
