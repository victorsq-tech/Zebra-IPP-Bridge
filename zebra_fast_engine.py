"""Fast, byte-exact ZPL ^GFA encoder and bounded Windows spool batching.

Works with Python 3.11+, Pillow and the existing print_pdf_zebra.send_raw().
Does not change the printer's persistent settings (no ^JUS).
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import binascii
import zlib
from PIL import Image


@dataclass(frozen=True)
class ZebraProfile:
    width: int = 480
    length: int = 879
    orientation: str = 'N'


PROFILE = ZebraProfile()

# Pillow performs the thresholding + 1-bit pack in C.
# In Pillow mode '1', a SET bit represents white; the inverse LUT below makes
# a SET bit represent *black*, as required by ZPL ^GFA.
_LUT_CACHE: dict[int, list[int]] = {}


def _threshold_lut(threshold: int) -> list[int]:
    if not 0 <= threshold <= 255:
        raise ValueError('threshold deve estar entre 0 e 255')
    lut = _LUT_CACHE.get(threshold)
    if lut is None:
        lut = [255 if x < threshold else 0 for x in range(256)]
        _LUT_CACHE[threshold] = lut
    return lut


def monochrome_image(image: Image.Image, threshold: int = 180) -> Image.Image:
    """1-bit raster, black foreground, white background, no Python pixel loops."""
    if image.mode != 'L':
        image = image.convert('L')
    return image.point(_threshold_lut(threshold), mode='1')


def encode_gfa(image: Image.Image, *, threshold: int = 180,
               profile: ZebraProfile = PROFILE, copies: int = 1,
               copies_strategy: str = 'repeat', encoding: str = 'hex') -> bytes:
    """Return a complete ZPL label, preserving physical ^PW/^LL.

    copies_strategy='zpl' uses ^PQ to ask the printer to repeat a page; opt-in
    only because its behavior should be verified with the installed firmware.
    copies_strategy='repeat' encodes one label and allows the caller to repeat.
    """
    if image.size != (profile.width, profile.length):
        raise ValueError(f'Raster de {image.size}, esperado {(profile.width, profile.length)}')
    if not 1 <= copies <= 9999:
        raise ValueError('copies fora do intervalo 1..9999')
    if copies_strategy not in ('repeat', 'zpl'):
        raise ValueError('copies_strategy deve ser repeat ou zpl')
    if encoding not in ('hex', 'z64'):
        raise ValueError('encoding deve ser hex ou z64')

    mono = monochrome_image(image, threshold)
    payload = mono.tobytes()  # bitmap ja empacotado, MSB-first por linha
    row_bytes = (profile.width + 7) // 8
    expected = row_bytes * profile.length
    if len(payload) != expected:
        raise ValueError(f'Empacotamento 1-bit inesperado: {len(payload)} != {expected}')
    if encoding == 'hex':
        data = payload.hex().upper().encode('ascii')  # fast C implementation
    else:
        # Official ZPL B64/Z64 format. CRC-16/XMODEM on *base64* bytes.
        base64_payload = base64.b64encode(zlib.compress(payload, level=6))
        crc = binascii.crc_hqx(base64_payload, 0)
        data = b':Z64:' + base64_payload + f':{crc:04X}'.encode('ascii')
    header = (
        f'^XA\n^PO{profile.orientation}\n^PW{profile.width}\n'
        f'^LL{profile.length}\n^LH0,0\n^LS0\n'
        f'^FO0,0^GFA,{expected},{expected},{row_bytes},'
    ).encode('ascii')
    quantity = (f'^PQ{copies}\n'.encode('ascii') if copies_strategy == 'zpl' and copies > 1 else b'')
    return header + data + b'^FS\n' + quantity + b'^XZ\n'


class SpoolBatch:
    """Send multiple ^XA...^XZ labels in bounded RAW Windows jobs.

    Keep the number of StartDocPrinter/EndDocPrinter calls low, but never
    accumulate unbounded data. Set max_labels=1 to disable batching.
    """
    def __init__(self, send_raw, printer, *, max_labels=16, max_bytes=2 * 1024 * 1024):
        if max_labels < 1 or max_bytes < 1024:
            raise ValueError('Limites de lote invalidos')
        self.send_raw = send_raw
        self.printer = printer
        self.max_labels = max_labels
        self.max_bytes = max_bytes
        self.pending = []
        self.bytes = 0
        self.labels = 0
        self.submitted = 0
        self.last_spooler_job = None

    def add(self, zpl: bytes, *, labels: int = 1):
        if not isinstance(zpl, bytes) or not zpl.startswith(b'^XA') or b'^XZ' not in zpl:
            raise ValueError('Trabalho ZPL invalido')
        if labels < 1:
            raise ValueError('labels deve ser positivo')
        if self.pending and (self.labels + labels > self.max_labels or self.bytes + len(zpl) > self.max_bytes):
            self.flush()
        self.pending.append(zpl)
        self.labels += labels
        self.bytes += len(zpl)
        if self.labels >= self.max_labels or self.bytes >= self.max_bytes:
            self.flush()

    def flush(self):
        if not self.pending:
            return None
        payload = b''.join(self.pending)
        # On failure keep the pending buffer for visibility / retry by caller.
        job_id = self.send_raw(payload, self.printer)
        self.submitted += self.labels
        self.last_spooler_job = job_id
        self.pending.clear()
        self.labels = 0
        self.bytes = 0
        return job_id
