"""Converte páginas PDF para ZPL ^GFA e envia como RAW ao spooler Windows.

Uso:
  py print_pdf_zebra.py "C:\\Etiquetas\\teste.pdf" --preview
  py print_pdf_zebra.py "C:\\Etiquetas\\teste.pdf"
"""
import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import pymupdf as fitz
from PIL import Image

PRINTER = "ZDesigner ZD220-203dpi ZPL"
DOTS_PER_MM = 8
PRINT_WIDTH = 480   # largura lógica invertida: 60 mm
PRINT_HEIGHT = 832  # altura lógica invertida: 104 mm (limite imprimível)
# Orientação ZPL normal: 0 graus (^PON). Corrige conteúdo lateral 90° anti-horário.


def render_page(page):
    """Renderiza o PDF, corrige a orientacao e SO ENTAO ajusta a etiqueta."""
    rect = page.rect
    # Renderiza com boa definicao; nunca encaixa antes de girar.
    scale = max(2.0, min(3.0, 1400 / max(rect.width, rect.height)))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    # O PDF de origem ja tem conteudo lateral: corrigir 90 graus anti-horario.
    # Esta e a direcao oposta a da versao anterior, cuja previa ficou vertical.
    image = image.transpose(Image.Transpose.ROTATE_90)
    # Rotação final para colocar a composição na orientação vertical da página.
    # A transformação total equivale a 90 graus horários em relação ao PDF original.
    image.thumbnail((PRINT_WIDTH, PRINT_HEIGHT), Image.Resampling.LANCZOS)
    result = Image.new("L", (PRINT_WIDTH, PRINT_HEIGHT), 255)
    result.paste(image, ((PRINT_WIDTH - image.width)//2, (PRINT_HEIGHT - image.height)//2))
    return result



def image_to_zpl(image, threshold=180):
    """Converte imagem em ZPL ^GFA (preto = bit 1)."""

    # Converter para tons de cinza
    gray = image.convert("L")

    # Converter para preto e branco
    mono = gray.point(
        lambda p: 0 if p < threshold else 255,
        mode="1"
    )

    width, height = mono.size
    bytes_per_row = math.ceil(width / 8)
    pixels = mono.load()
    payload = bytearray()

    for y in range(height):
        for x0 in range(0, width, 8):
            byte = 0

            for bit in range(8):
                x = x0 + bit

                if x < width and pixels[x, y] == 0:
                    byte |= 1 << (7 - bit)

            payload.append(byte)

    count = len(payload)

    return (
        f"^XA\n^PON\n^PW{width}\n^LL{height}\n^LH0,0\n"
        f"^FO0,0^GFA,{count},{count},{bytes_per_row},"
        f"{payload.hex().upper()}^FS\n^XZ\n"
    ).encode("ascii")



def send_raw(zpl, printer_name):
    """Envia ZPL como RAW para uma fila instalada no Windows."""
    if sys.platform != "win32":
        raise RuntimeError("O envio RAW requer Windows e pywin32.")
    import win32print

    handle = win32print.OpenPrinter(printer_name)
    try:
        job_id = win32print.StartDocPrinter(
            handle, 1, ("Etiqueta PDF ZPL", None, "RAW")
        )
        try:
            win32print.StartPagePrinter(handle)
            try:
                written = win32print.WritePrinter(handle, zpl)
                if written != len(zpl):
                    raise IOError(f"Envio incompleto: {written}/{len(zpl)} bytes")
            finally:
                win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
        return job_id
    finally:
        win32print.ClosePrinter(handle)


def main():
    parser = argparse.ArgumentParser(
        description="Imprime PDF na Zebra ZD220 (layout lógico 480 x 832 dots)"
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--printer", default=PRINTER)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "previews", help="Pasta das prévias")
    parser.add_argument("--threshold", type=int, default=180)
    parser.add_argument(
        "--preview", action="store_true",
        help="Salva PNG e ZPL sem enviar para a impressora"
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        parser.error(f"PDF não encontrado: {args.pdf}")
    if not 0 <= args.threshold <= 255:
        parser.error("--threshold deve estar entre 0 e 255")

    doc = fitz.open(args.pdf)
    try:
        if doc.page_count == 0:
            parser.error("O PDF não contém páginas.")
        if args.preview:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for index, page in enumerate(doc, start=1):
            image = render_page(page)
            zpl = image_to_zpl(image, args.threshold)

            if args.preview:
                stem = args.output_dir / f"{args.pdf.stem}_pagina_{index}_{run_id}"
                image.save(stem.with_suffix(".png"))
                stem.with_suffix(".zpl").write_bytes(zpl)
                print(f"Prévia criada: {stem.with_suffix('.png')}")
                print(f"ZPL criado: {stem.with_suffix('.zpl')}")
            else:
                job_id = send_raw(zpl, args.printer)
                print(
                    f"Página {index}/{doc.page_count} enviada. "
                    f"Trabalho Windows: {job_id}"
                )
    finally:
        doc.close()


if __name__ == "__main__":
    main()
