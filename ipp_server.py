"""Ponte IPP experimental: Android -> PDF/JPEG/PNG -> imagem -> ZPL -> Zebra ZD220 USB.

PERFIL TESTE: etiqueta Zebra Utilities, largura ^PW480, comprimento ^LL879.
ATENCAO: do not send configuration file with ^JUS to printer during testing.


IMPORTANTE
- Compatibilidade Android previamente testada pelo usuario em modo PDF.
- JPEG/PNG e autodeteccao de formato implementados, aguardando testes no tablet.
- Este projeto NAO implementa IPP Everywhere nem possui certificacao Mopria.
- Sem --print NENHUM dado e enviado a impressora.
- A previa *_zpl.png e o raster preto/branco EXATO passado a image_to_zpl().
- Com --print, o recebimento pelo spooler nao garante impressao fisica correta.

Requer: pymupdf, pillow, zeroconf e o modulo local print_pdf_zebra.py.
Em Windows, o envio RAW requer pywin32 (utilizado pelo modulo de impressao).

Exemplos:
  py ipp_server.py --ip 192.168.10.76
  py ipp_server.py --ip 192.168.10.76 --test-pdf "C:\\Etiquetas\\teste.pdf"
  py ipp_server.py --ip 192.168.10.76 --calibrate
  py ipp_server.py --ip 192.168.10.76 --calibrate --rotation 0 --print
  py ipp_server.py --ip 192.168.10.76 --rotation 0 --print
  py ipp_server.py --ip 192.168.10.76 --rotation 180 --print
  py ipp_server.py --ip 192.168.10.76 --port 631 --max-pdf-pages 1000 --max-labels-per-job 1000 --debug
  py ipp_server.py --ip 192.168.10.76 --rotation 0 --offset-x 8 --offset-y -4 --print
"""

import argparse
from io import BytesIO
from datetime import datetime
import logging
from pathlib import Path
import socket
import struct
import threading
import queue
import shutil
from tempfile import SpooledTemporaryFile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymupdf
from PIL import Image, ImageDraw, ImageOps
from print_pdf_zebra import PRINTER, render_page, send_raw
from zebra_fast_engine import encode_gfa, SpoolBatch, ZebraProfile
from zebra_formatter import LayoutOptions, format_pdf_page, format_source_image, binarize

LOG = logging.getLogger('zebra-ipp')

# Marcadores IPP (RFC 8010): preservar o protocolo que ja funciona no tablet.
OP, JOB, PRINTER_GROUP, END = 0x01, 0x02, 0x04, 0x03
INTEGER, BOOLEAN, ENUM = 0x21, 0x22, 0x23
RESOLUTION, RANGE = 0x32, 0x33
BEGIN_COLLECTION, END_COLLECTION, MEMBER_NAME = 0x34, 0x37, 0x4A
TEXT, NAME, KEYWORD, URI, MIME, CHARSET, LANG = (
    0x41, 0x42, 0x44, 0x45, 0x49, 0x47, 0x48
)
# Limites de lotes: cada pagina do PDF = uma etiqueta distinta.
# O Android pode enviar tambem o atributo IPP 'copies' para repetir cada pagina.
MAX_REQUEST = 100 * 1024 * 1024
MAX_PDF_PAGES = 500
HARD_MAX_PDF_PAGES = 5000
MAX_COPIES = 50
MAX_LABELS_PER_JOB = 1000
MAX_QUEUE_JOBS = 8
MAX_QUEUE_BYTES = 400 * 1024 * 1024
MAX_HISTORY = 250
HTTP_MEMORY_THRESHOLD = 2 * 1024 * 1024
HTTP_IO_CHUNK = 512 * 1024
HARD_MAX_LABELS_PER_JOB = 5000
# So anunciar formatos que sabemos decodificar. PWG Raster/PCLm/URF ainda nao.
SUPPORTED_DOCUMENT_FORMATS = ('application/pdf', 'image/jpeg', 'image/png')
AUTO_DETECT_FORMAT = 'application/octet-stream'  # fallback aceito, nao anunciado
MAX_IMAGE_PIXELS = 25_000_000  # proteger contra imagens gigantes compactadas
MEDIA = 'custom_110x60mm_110x60mm'

# Perfil extraido do arquivo "Etiqueta Grande.zpl" gerado pelo Zebra Utilities.
# O driver usa 60 mm no eixo transversal da cabeca (~480 dots)
# e 110 mm no sentido de avanco (~879 dots), a 203 dpi.
# OBS.: o Android ainda anuncia o formato logico 110x60 mm; nao alterar
# os atributos IPP sem testar novamente a compatibilidade do tablet.
ZPL_WIDTH = 480    # ^PW480: largura fisica utilizada pelo driver
ZPL_LENGTH = 879   # ^LL879: comprimento da etiqueta no avanco do papel

BAD_REQUEST, UNSUPPORTED, NOT_FOUND = 0x0400, 0x040B, 0x0406
jobs = {}
job_lock = threading.Lock()
next_job = 1
started = time.monotonic()


class JobCanceled(Exception):
    """Cancelamento entre paginas, sem reverter dados ja enviados ao spooler."""


def job_canceled(jid):
    if not isinstance(jid, int):
        return False
    with job_lock:
        return jobs.get(jid, {}).get('state') == 7


def check_job_canceled(jid):
    if job_canceled(jid):
        raise JobCanceled(f'Trabalho {jid} cancelado pelo usuario')

PRINTER_UUID = 'urn:uuid:' + str(uuid.uuid5(
    uuid.NAMESPACE_DNS, 'zebra-zd220-ipp-pdf-bridge-v1'
))


def value_bytes(tag, value):
    if tag in (INTEGER, ENUM):
        return struct.pack('>i', int(value))
    if tag == BOOLEAN:
        return bytes((int(bool(value)),))
    if tag == RANGE:
        return struct.pack('>ii', *value)
    if tag == RESOLUTION:
        x, y, units = value
        return struct.pack('>iiB', x, y, units)
    if value is None or value == b'':
        return b''
    if isinstance(value, bytes):
        return value
    return str(value).encode('utf-8')


def attr(tag, name, values):
    values = values if isinstance(values, list) else [values]
    result = bytearray()
    for index, value in enumerate(values):
        name_raw = name.encode('utf-8') if index == 0 else b''
        raw = value_bytes(tag, value)
        result.extend(struct.pack('>BH', tag, len(name_raw)))
        result.extend(name_raw)
        result.extend(struct.pack('>H', len(raw)))
        result.extend(raw)
    return bytes(result)


def collection(name, members):
    result = bytearray(attr(BEGIN_COLLECTION, name, b''))
    for member_name, tag, value in members:
        result.extend(attr(MEMBER_NAME, '', member_name))
        if tag == BEGIN_COLLECTION:
            result.extend(collection('', value))
        else:
            result.extend(attr(tag, '', value))
    result.extend(attr(END_COLLECTION, '', b''))
    return bytes(result)


def media_collection():
    return [
        ('media-key', KEYWORD, MEDIA),
        ('media-size', BEGIN_COLLECTION, [
            ('x-dimension', INTEGER, 11000),
            ('y-dimension', INTEGER, 6000),
        ]),
        ('media-type', KEYWORD, 'labels'),
        ('media-left-margin', INTEGER, 0),
        ('media-right-margin', INTEGER, 0),
        ('media-top-margin', INTEGER, 0),
        ('media-bottom-margin', INTEGER, 0),
    ]


def group(tag, items):
    result = bytearray((tag,))
    for value_tag, name, value in items:
        if value_tag == BEGIN_COLLECTION:
            result.extend(collection(name, value))
        else:
            result.extend(attr(value_tag, name, value))
    return bytes(result)


def response(version, status, reqid, groups=()):
    return (
        version + struct.pack('>HI', status, reqid)
        + group(OP, [
            (CHARSET, 'attributes-charset', 'utf-8'),
            (LANG, 'attributes-natural-language', 'en'),
        ])
        + b''.join(group(*g) for g in groups)
        + bytes((END,))
    )


def parse(payload):
    if len(payload) < 9:
        raise ValueError('IPP curto')
    version = payload[:2]
    operation, reqid = struct.unpack_from('>HI', payload, 2)
    offset, attrs, last = 8, {}, None
    while offset < len(payload):
        tag = payload[offset]
        offset += 1
        if tag == END:
            return version, operation, reqid, attrs, payload[offset:]
        if tag <= 0x0F:
            last = None
            continue
        if offset + 4 > len(payload):
            raise ValueError('Atributo IPP truncado')
        name_len = struct.unpack_from('>H', payload, offset)[0]
        offset += 2
        if offset + name_len + 2 > len(payload):
            raise ValueError('Nome IPP truncado')
        name = payload[offset:offset + name_len].decode('utf-8', 'replace')
        offset += name_len
        value_len = struct.unpack_from('>H', payload, offset)[0]
        offset += 2
        if offset + value_len > len(payload):
            raise ValueError('Valor IPP truncado')
        raw = payload[offset:offset + value_len]
        offset += value_len
        if name:
            last = name
        if last:
            if tag in (INTEGER, ENUM) and len(raw) == 4:
                value = struct.unpack('>i', raw)[0]
            elif tag == BOOLEAN and len(raw) == 1:
                value = bool(raw[0])
            else:
                value = raw.decode('utf-8', 'replace')
            attrs.setdefault(last, []).append(value)
    raise ValueError('IPP sem end-of-attributes-tag')


def parse_stream(stream):
    """Parse only IPP headers; keep the document in a seekable file.

    Returns (version, op, reqid, attrs, document_offset).  No document copy.
    """
    stream.seek(0)
    head = stream.read(8)
    if len(head) != 8:
        raise ValueError('IPP curto')
    version, operation, reqid = head[:2], *struct.unpack('>HI', head[2:8])
    attrs, last = {}, None
    while True:
        marker = stream.read(1)
        if not marker:
            raise ValueError('IPP sem end-of-attributes-tag')
        tag = marker[0]
        if tag == END:
            return version, operation, reqid, attrs, stream.tell()
        if tag <= 0x0F:
            last = None
            continue
        nbytes = stream.read(2)
        if len(nbytes) != 2:
            raise ValueError('Atributo IPP truncado')
        nl = struct.unpack('>H', nbytes)[0]
        name_bytes = stream.read(nl)
        if len(name_bytes) != nl:
            raise ValueError('Nome IPP truncado')
        vl_bytes = stream.read(2)
        if len(vl_bytes) != 2:
            raise ValueError('Comprimento de valor IPP truncado')
        vl = struct.unpack('>H', vl_bytes)[0]
        raw = stream.read(vl)
        if len(raw) != vl:
            raise ValueError('Valor IPP truncado')
        name = name_bytes.decode('utf-8', 'replace')
        if name:
            last = name
        if last:
            if tag in (INTEGER, ENUM) and len(raw) == 4:
                value = struct.unpack('>i', raw)[0]
            elif tag == BOOLEAN and len(raw) == 1:
                value = bool(raw[0])
            else:
                value = raw.decode('utf-8', 'replace')
            attrs.setdefault(last, []).append(value)


def first(attrs, key, default=None):
    return attrs.get(key, [default])[0]


def quantidade_copias(attrs):
    """Valida copies do IPP; uma pagina PDF pode ser repetida N vezes."""
    valor = first(attrs, 'copies', 1)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f'copies invalido (tipo): {valor!r}')
    if not 1 <= valor <= MAX_COPIES:
        raise ValueError(f'copies deve estar entre 1 e {MAX_COPIES}, recebeu {valor}')
    return valor


def printer_attrs(uri):
    with job_lock:
        active = sum(job['state'] in (3, 4, 5, 6) for job in jobs.values())
    return [
        (URI, 'printer-uri-supported', uri),
        (NAME, 'printer-name', 'Zebra ZD220 IPP Etiquetas'),
        (TEXT, 'printer-info', 'Zebra ZD220 USB via ponte IPP PDF/JPEG/PNG'),
        (NAME, 'printer-make-and-model', 'Zebra ZD220 203dpi ZPL Bridge'),
        (URI, 'printer-uuid', PRINTER_UUID),
        (KEYWORD, 'uri-security-supported', 'none'),
        (KEYWORD, 'uri-authentication-supported', 'none'),
        (KEYWORD, 'ipp-versions-supported', ['1.1', '2.0']),
        (ENUM, 'operations-supported', [0x0002, 0x0004, 0x0008, 0x0009, 0x000A, 0x000B]),
        (MIME, 'document-format-supported', list(SUPPORTED_DOCUMENT_FORMATS)),
        (MIME, 'document-format-default', 'application/pdf'),
        (MIME, 'document-format-preferred', 'application/pdf'),
        (ENUM, 'printer-state', 3),
        (BOOLEAN, 'printer-is-accepting-jobs', True),
        (KEYWORD, 'printer-state-reasons', 'none'),
        (INTEGER, 'queued-job-count', active),
        (INTEGER, 'printer-up-time', max(1, int(time.monotonic() - started))),
        (KEYWORD, 'pdl-override-supported', 'not-attempted'),
        (RANGE, 'copies-supported', (1, MAX_COPIES)),
        (INTEGER, 'copies-default', 1),
        (KEYWORD, 'sides-supported', 'one-sided'),
        (KEYWORD, 'sides-default', 'one-sided'),
        (BOOLEAN, 'color-supported', False),
        (KEYWORD, 'print-color-mode-supported', 'monochrome'),
        (KEYWORD, 'print-color-mode-default', 'monochrome'),
        (RESOLUTION, 'printer-resolution-supported', (203, 203, 3)),
        (RESOLUTION, 'printer-resolution-default', (203, 203, 3)),
        (KEYWORD, 'print-scaling-supported', ['auto', 'fit', 'none']),
        (KEYWORD, 'print-scaling-default', 'fit'),
        (KEYWORD, 'media-default', MEDIA),
        (KEYWORD, 'media-supported', MEDIA),
        (KEYWORD, 'media-ready', MEDIA),
        (BEGIN_COLLECTION, 'media-col-default', media_collection()),
        (BEGIN_COLLECTION, 'media-col-ready', media_collection()),
        (BEGIN_COLLECTION, 'media-col-database', media_collection()),
        (KEYWORD, 'media-col-supported', [
            'media-size', 'media-type', 'media-key',
            'media-left-margin', 'media-right-margin',
            'media-top-margin', 'media-bottom-margin',
        ]),
        (INTEGER, 'media-left-margin-supported', 0),
        (INTEGER, 'media-right-margin-supported', 0),
        (INTEGER, 'media-top-margin-supported', 0),
        (INTEGER, 'media-bottom-margin-supported', 0),
        (KEYWORD, 'media-type-supported', 'labels'),
        (KEYWORD, 'media-type-default', 'labels'),
    ]


def job_attrs(job, uri):
    return [
        (INTEGER, 'job-id', job['id']),
        (URI, 'job-uri', uri + '/jobs/' + str(job['id'])),
        (URI, 'job-printer-uri', uri),
        (ENUM, 'job-state', job['state']),
        (KEYWORD, 'job-state-reasons', job['reason']),
        (NAME, 'job-name', job['name']),
        (INTEGER, 'job-impressions-completed', job.get('labels_done', 0)),
    ]


def ampliar_etiqueta(image, margem=12):
    """Recorta branco excedente e amplia sem distorcer a proporcao da etiqueta."""
    image = image.convert('RGB')
    largura, altura = image.size
    cinza = ImageOps.grayscale(image)
    mascara = cinza.point(lambda pixel: 255 if pixel < 240 else 0)
    bbox = mascara.getbbox()
    if bbox is None:
        LOG.warning('Pagina branca: sem conteudo para ampliar')
        return image

    conteudo = image.crop(bbox)
    disponivel = (max(1, largura - 2 * margem), max(1, altura - 2 * margem))
    conteudo = ImageOps.contain(conteudo, disponivel, Image.Resampling.LANCZOS)
    resultado = Image.new('RGB', (largura, altura), 'white')
    x = (largura - conteudo.width) // 2
    y = (altura - conteudo.height) // 2
    resultado.paste(conteudo, (x, y))
    LOG.info('Etiqueta ampliada: bbox=%s; conteudo=%s; final=%s',
             bbox, conteudo.size, resultado.size)
    return resultado


def preparar_imagem_zpl(imagem, *, rotation, crop_margin, safe_margin,
                         offset_x, offset_y, scale, auto_crop=True):
    """Unico caminho de rotacao, escala e posicionamento de PDF e calibracao.

    O resultado segue o driver Zebra: 480x879 dots (largura x avanco).
    O motor render_page() antigo ja devolve um raster vertical 480x832.
    Portanto, NAO fazer outra rotacao por padrao (rotation=0).
    Rotacoes Pillow: 90=anti-horaria; 270=horaria.
    """
    LOG.info('Raster inicial: %s', imagem.size)
    if auto_crop:
        imagem = ampliar_etiqueta(imagem, margem=crop_margin)
    else:
        imagem = imagem.convert('RGB')

    rotations = {
        0: None,
        90: Image.Transpose.ROTATE_90,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_270,
    }
    if rotation:
        imagem = imagem.transpose(rotations[rotation])

    useful_w = ZPL_WIDTH - 2 * safe_margin
    useful_h = ZPL_LENGTH - 2 * safe_margin
    caber = ImageOps.contain(imagem, (useful_w, useful_h), Image.Resampling.LANCZOS)
    if scale != 1:
        caber = caber.resize((
            max(1, round(caber.width * scale)),
            max(1, round(caber.height * scale)),
        ), Image.Resampling.LANCZOS)

    final = Image.new('RGB', (ZPL_WIDTH, ZPL_LENGTH), 'white')
    x = (ZPL_WIDTH - caber.width) // 2 + offset_x
    y = (ZPL_LENGTH - caber.height) // 2 + offset_y
    if x < 0 or y < 0 or x + caber.width > ZPL_WIDTH or y + caber.height > ZPL_LENGTH:
        LOG.warning('Deslocamento produz corte no raster: pos=(%d,%d), tamanho=%s',
                    x, y, caber.size)
    final.paste(caber, (x, y))
    LOG.info('Raster ZPL final: %s, rotacao=%d, posicao=(%d,%d), escala=%s',
             final.size, rotation, x, y, scale)
    return final


def format_options(server):
    return LayoutOptions(
        width=ZPL_WIDTH, length=ZPL_LENGTH,
        crop_margin=server.crop_margin, safe_margin=server.safe_margin,
        rotation=server.rotation, content_orientation=getattr(server, 'content_orientation', 'auto'),
        scale=server.scale, offset_x=server.offset_x, offset_y=server.offset_y,
        align_x=getattr(server, 'align_x', 'center'), align_y=getattr(server, 'align_y', 'center'),
        auto_crop=server.auto_crop, trim_threshold=getattr(server, 'trim_threshold', 245),
        render_factor=getattr(server, 'render_factor', 2.0),
    )


def preparar_raster_zpl(page, *, server):
    """Modo smart: detecta bbox em PDF e renderiza apenas a etiqueta em alta resolucao.

    Modo legacy usa render_page() do usuario, para regressao/calibracao.
    """
    if getattr(server, 'layout_mode', 'smart') == 'smart':
        raster, info = format_pdf_page(page, format_options(server))
        LOG.debug('LAYOUT PDF detalhado: %s', info.to_dict())
        return raster
    return preparar_imagem_zpl(
        render_page(page), rotation=server.rotation, crop_margin=server.crop_margin,
        safe_margin=server.safe_margin, offset_x=server.offset_x,
        offset_y=server.offset_y, scale=server.scale, auto_crop=server.auto_crop,
    )


def raster_calibracao():
    """Padrao assimetrico no formato do driver (480x879 dots).

    Nao passa por recorte automatico; permite verificar o limite da etiqueta,
    o sentido de avanco e eventuais deslocamentos fisicos.
    """
    largura, altura = ZPL_WIDTH, ZPL_LENGTH
    imagem = Image.new('RGB', (largura, altura), 'white')
    desenho = ImageDraw.Draw(imagem)

    desenho.rectangle((24, 24, largura - 25, altura - 25),
                      outline='black', width=4)
    desenho.text((145, 50), 'TOPO / TOP', fill='black')
    desenho.text((35, 96), 'ROTACAO: MARCAS DIFERENTES', fill='black')

    # 4 cantos diferentes: TL=circulo; TR=quadrado; BL=X; BR=triangulo.
    desenho.ellipse((42, 42, 77, 77), fill='black')
    desenho.rectangle((largura - 82, 42, largura - 46, 78), fill='black')
    desenho.line((43, altura - 80, 80, altura - 43), fill='black', width=6)
    desenho.line((43, altura - 43, 80, altura - 80), fill='black', width=6)
    desenho.polygon([(largura - 70, altura - 84),
                     (largura - 43, altura - 44),
                     (largura - 97, altura - 44)], fill='black')

    # Eixos desenhados no formato original, antes da rotacao solicitada.
    desenho.text((135, 175), 'X: DIREITA', fill='black')
    desenho.line((90, 215, largura - 95, 215), fill='black', width=6)
    desenho.polygon([(largura - 95, 196), (largura - 55, 215),
                     (largura - 95, 234)], fill='black')

    desenho.text((100, 275), 'Y: BAIXO', fill='black')
    desenho.line((100, 315, 100, altura - 170), fill='black', width=6)
    desenho.polygon([(81, altura - 170), (100, altura - 130),
                     (119, altura - 170)], fill='black')
    desenho.text((160, altura - 140), 'BASE VERTICAL', fill='black')
    desenho.text((160, altura - 115), '480 x 879', fill='black')
    return imagem


def salvar_artefatos(preview_dir, prefix, raster, zpl):
    preview_dir.mkdir(parents=True, exist_ok=True)
    nome = f'{prefix}_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}_{uuid.uuid4().hex[:6]}'
    caminho_png = preview_dir / f'{nome}_zpl.png'
    caminho_zpl = preview_dir / f'{nome}.zpl'
    raster.save(caminho_png, format='PNG')
    caminho_zpl.write_bytes(zpl)
    LOG.info('PREVIA EXATA ZPL: %s (tamanho=%s)', caminho_png, raster.size)
    LOG.info('Arquivo ZPL: %s (%d bytes)', caminho_zpl, len(zpl))
    return caminho_png, caminho_zpl


def raster_preto_branco(raster, threshold=180, mode='fixed'):
    """Previas e ^GFA usam exatamente os mesmos pixels 0/255."""
    result, selected = binarize(raster, threshold=threshold, mode=mode)
    LOG.debug('Binarizacao %s: limiar efetivo=%d', mode, selected)
    return result


def codificar_zpl(raster, *, compression='hex'):
    """Empacotamento 1-bit no Pillow (C), sem loops Python por pixel."""
    return encode_gfa(
        raster, threshold=180,
        profile=ZebraProfile(width=ZPL_WIDTH, length=ZPL_LENGTH),
        encoding=compression,
    )


def criar_spool_batch(server, print_real):
    if not print_real:
        return None
    return SpoolBatch(
        send_raw, server.printer,
        max_labels=getattr(server, 'spool_batch_labels', 16),
        max_bytes=getattr(server, 'spool_batch_bytes', 2 * 1024 * 1024),
    )


def enviar_copias(batch, zpl, copies, *, server):
    if batch is None:
        return
    if getattr(server, 'copies_strategy', 'repeat') == 'zpl' and copies > 1:
        # ^PQ is optional to preserve compatibility with existing firmware.
        zpl_qty = zpl.replace(b'^XZ', f'^PQ{copies}\n^XZ'.encode('ascii'), 1)
        batch.add(zpl_qty, labels=copies)
    else:
        for _ in range(copies):
            batch.add(zpl)


def registrar_progresso(jid, *, pages=0, labels=0):
    if not isinstance(jid, int):
        return
    with job_lock:
        job = jobs.get(jid)
        if job:
            job['pages_done'] = pages
            job['labels_done'] = labels


def salvar_se_necessario(server, prefix, raster, zpl, print_real):
    # In production skip expensive disk writes unless explicitly requested.
    if not print_real or getattr(server, 'save_print_previews', False):
        salvar_artefatos(server.preview_dir, prefix, raster, zpl)


def processar_pdf(document, *, server, jid, print_real, copies=1):
    """Processa uma pagina por vez e agrupa envios RAW ao spooler.

    document: bytes para testes locais, ou Path para trabalhos da fila.
    """
    source_kwargs = ({'filename': str(document)} if isinstance(document, Path)
                     else {'stream': document, 'filetype': 'pdf'})
    with pymupdf.open(**source_kwargs) as pdf:
        paginas = len(pdf)
        limite = getattr(server, 'max_pdf_pages', MAX_PDF_PAGES)
        LOG.info('PDF recebido: paginas=%d; limite=%d', paginas, limite)
        if paginas == 0:
            raise ValueError('PDF sem paginas')
        if paginas > limite:
            raise ValueError(f'PDF tem {paginas} paginas; limite {limite}. Confira a midia A4 no Android.')
        total = paginas * copies
        if total > server.max_labels_per_job:
            raise ValueError(f'Lote {total} excede {server.max_labels_per_job} etiquetas')
        LOG.info('LOTE: %d paginas x %d copias = %d etiquetas', paginas, copies, total)
        batch = criar_spool_batch(server, print_real)
        for i, page in enumerate(pdf, 1):
            check_job_canceled(jid)
            raster = preparar_raster_zpl(page, server=server)
            raster_binario = raster_preto_branco(
                raster, threshold=server.threshold,
                mode=getattr(server, 'binarization', 'fixed'))
            zpl = codificar_zpl(raster_binario, compression=getattr(server, 'zpl_compression', 'hex'))
            salvar_se_necessario(server, f'job_{jid}_pagina_{i}', raster_binario, zpl, print_real)
            check_job_canceled(jid)
            enviar_copias(batch, zpl, copies, server=server)
            registrar_progresso(jid, pages=i, labels=i * copies)
            if i == 1 or i % 25 == 0 or i == paginas:
                LOG.info('LOTE %s: %d/%d paginas preparadas', jid, i, paginas)
        if batch is not None:
            batch.flush()
            LOG.info('LOTE %s: %d etiquetas enviadas em lotes RAW', jid, batch.submitted)
        else:
            LOG.info('LOTE %s: %d etiquetas simuladas em previa', jid, total)


def detectar_formato(document):
    """Identifica apenas os tres formatos que o motor realmente suporta."""
    if document.startswith(b'%PDF-'):
        return 'application/pdf'
    if document.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if document.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    return None


def formato_aceito(declarado, document=None):
    """Devolve o MIME efetivo ou None para conteudo/tipo nao aceito.

    A falta de document-format permite autodeteccao em Print-Job;
    Validate-Job nao traz documento e valida somente o formato declarado.
    """
    declarado = (declarado or '').strip().lower()
    if document is None:
        if declarado in SUPPORTED_DOCUMENT_FORMATS or declarado in ('', AUTO_DETECT_FORMAT):
            return declarado or 'application/pdf'
        return None
    detectado = detectar_formato(document)
    if detectado is None:
        return None
    if declarado in ('', AUTO_DETECT_FORMAT, detectado):
        return detectado
    return None


def raster_de_imagem(document, mime, *, preserve_original=False):
    """Abre JPEG/PNG sem perder orientacao EXIF e encaixa no raster logico.

    O PDF no projeto ja chegava ao pipeline em 480x832; imagens horizontais
    sao giradas para utilizar a mesma base vertical de composicao.
    """
    try:
        with Image.open(document if isinstance(document, Path) else BytesIO(document)) as origem:
            if origem.format not in ('JPEG', 'PNG'):
                raise ValueError('Formato de imagem nao reconhecido pelo Pillow')
            if origem.width * origem.height > MAX_IMAGE_PIXELS:
                raise ValueError('Imagem excede limite de pixels')
            imagem = ImageOps.exif_transpose(origem)
            imagem.load()
            # PNGs transparentes devem ser compostos sobre BRANCO, nao preto.
            rgba = imagem.convert('RGBA')
            fundo = Image.new('RGBA', rgba.size, 'white')
            fundo.alpha_composite(rgba)
            imagem = fundo.convert('RGB')
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f'Falha ao decodificar {mime}: {exc}') from exc

    if preserve_original:
        return imagem

    if imagem.width > imagem.height:
        imagem = imagem.transpose(Image.Transpose.ROTATE_90)

    # Reaproveita a mesma etapa de ampliacao, rotacao, corte e ^GFA do PDF.
    imagem = ImageOps.contain(imagem, (480, 832), Image.Resampling.LANCZOS)
    base = Image.new('RGB', (480, 832), 'white')
    base.paste(imagem, ((480 - imagem.width) // 2, (832 - imagem.height) // 2))
    LOG.info('Entrada %s convertida em raster logico %s', mime, base.size)
    return base


def processar_imagem(document, mime, *, server, jid, print_real, copies=1):
    if copies > server.max_labels_per_job:
        raise ValueError(f'{copies} copias excedem limite de {server.max_labels_per_job} etiquetas')
    check_job_canceled(jid)
    if getattr(server, 'layout_mode', 'smart') == 'smart':
        imagem = raster_de_imagem(document, mime, preserve_original=True)
        raster, info = format_source_image(imagem, format_options(server))
        LOG.debug('LAYOUT IMAGEM detalhado: %s', info.to_dict())
    else:
        imagem = raster_de_imagem(document, mime)
        raster = preparar_imagem_zpl(
            imagem, rotation=server.rotation, crop_margin=server.crop_margin,
            safe_margin=server.safe_margin, offset_x=server.offset_x,
            offset_y=server.offset_y, scale=server.scale, auto_crop=server.auto_crop,
        )
    raster_binario = raster_preto_branco(
        raster, threshold=server.threshold,
        mode=getattr(server, 'binarization', 'fixed'))
    zpl = codificar_zpl(raster_binario, compression=getattr(server, 'zpl_compression', 'hex'))
    salvar_se_necessario(server, f'job_{jid}_imagem', raster_binario, zpl, print_real)
    check_job_canceled(jid)
    batch = criar_spool_batch(server, print_real)
    enviar_copias(batch, zpl, copies, server=server)
    if batch is not None:
        batch.flush()
    registrar_progresso(jid, pages=1, labels=copies)
    LOG.info('IMAGEM %s: %d copia(s) processadas', mime, copies)


def processar_documento(document, mime, *, server, jid, print_real, copies=1):
    if mime == 'application/pdf':
        return processar_pdf(document, server=server, jid=jid, print_real=print_real, copies=copies)
    if mime in ('image/jpeg', 'image/png'):
        return processar_imagem(document, mime, server=server, jid=jid, print_real=print_real, copies=copies)
    raise ValueError(f'Formato nao implementado: {mime}')


def _liberar_spool(server, job):
    size = job.get('spool_bytes', 0)
    with server.queue_lock:
        server.queue_bytes = max(0, server.queue_bytes - size)
    try:
        Path(job['spool_path']).unlink(missing_ok=True)
    except OSError:
        LOG.exception('Nao foi possivel remover spool temporario do trabalho %s', job['id'])


def worker_de_impressao(server):
    """Um worker para preservar ordem dos trabalhos e limitar RAM."""
    while True:
        item = server.job_queue.get()
        if item is None:
            server.job_queue.task_done()
            return
        jid = item
        with job_lock:
            job = jobs[jid]
            if job['state'] == 7:
                canceled = True
            else:
                canceled = False
                job['state'], job['reason'] = 5, 'job-printing'
        try:
            if not canceled:
                LOG.info('WORKER: iniciando trabalho %d; formato=%s', jid, job['mime'])
                processar_documento(
                    Path(job['spool_path']), job['mime'], server=server, jid=jid,
                    print_real=not server.dry_run, copies=job['copies'],
                )
                with job_lock:
                    if job['state'] != 7:
                        job['state'] = 9
                        # O Windows aceitou o RAW, mas nao temos confirmacao da Zebra
                        # sobre a saida fisica. RFC 8011: queued-in-device.
                        job['reason'] = ('completed-successfully' if server.dry_run
                                         else 'queued-in-device')
                LOG.info('WORKER: trabalho %d enviado/concluido; paginas=%s; estado=%s razao=%s',
                         jid, job.get('pages_done'), job['state'], job['reason'])
        except JobCanceled:
            with job_lock:
                job['state'], job['reason'] = 7, 'job-canceled-by-user'
            LOG.info('WORKER: trabalho %d cancelado (dados ja enviados nao podem ser revertidos)', jid)
        except Exception:
            with job_lock:
                job['state'], job['reason'] = 8, 'job-aborted-by-system'
            LOG.exception('WORKER: falha no trabalho %d', jid)
        finally:
            _liberar_spool(server, job)
            server.job_queue.task_done()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def handle(self):
        """Ignora desconexoes normais de clientes HTTP sem ocultar outros erros."""
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
            LOG.debug(
                'Cliente %s:%s encerrou conexao TCP: %s',
                self.client_address[0], self.client_address[1], exc
            )

    def log_message(self, fmt, *args):
        # Consultas de acompanhamento do Android podem ocorrer ~1x/seg.
        # Mantemos no DEBUG para nao saturar a interface do gerenciador.
        level = logging.DEBUG if getattr(self, '_quiet_poll', False) else logging.INFO
        LOG.log(level, '%s ' + fmt, self.client_address[0], *args)

    def do_GET(self):
        data = b'Zebra IPP bridge online. Formatos: PDF, JPEG, PNG. Endpoint: /ipp/print\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_request(self):
        """Read HTTP body with bounded RAM; spill large uploads to temp disk."""
        self.connection.settimeout(120)
        transfer = self.headers.get('Transfer-Encoding', '').lower()
        chunked = 'chunked' in [x.strip() for x in transfer.split(',')]
        length = self.headers.get('Content-Length')
        if not chunked and length is None:
            raise ValueError('HTTP sem Content-Length nem Transfer-Encoding chunked')
        size = None if chunked else int(length)
        if size is not None and (size < 0 or size > MAX_REQUEST):
            raise OverflowError('Content-Length excede limite HTTP')
        sink = SpooledTemporaryFile(max_size=HTTP_MEMORY_THRESHOLD, mode='w+b')
        count = 0
        try:
            if chunked:
                while True:
                    line = self.rfile.readline(128)
                    if not line or not line.endswith(b'\r\n'):
                        raise ValueError('Cabecalho chunk invalido')
                    chunk_size = int(line.split(b';', 1)[0].strip(), 16)
                    if count + chunk_size > MAX_REQUEST:
                        raise OverflowError('Trabalho excede limite HTTP')
                    if chunk_size == 0:
                        while True:
                            trailer = self.rfile.readline(8192)
                            if trailer in (b'\r\n', b'\n'):
                                break
                            if not trailer:
                                raise ValueError('Trailer incompleto')
                        break
                    remaining = chunk_size
                    while remaining:
                        block = self.rfile.read(min(remaining, HTTP_IO_CHUNK))
                        if not block:
                            raise ValueError('Chunk incompleto')
                        sink.write(block)
                        remaining -= len(block)
                    if self.rfile.read(2) != b'\r\n':
                        raise ValueError('Separador chunk invalido')
                    count += chunk_size
            else:
                remaining = size
                while remaining:
                    block = self.rfile.read(min(remaining, HTTP_IO_CHUNK))
                    if not block:
                        raise ValueError('Corpo HTTP incompleto')
                    sink.write(block)
                    remaining -= len(block)
                count = size
            sink.seek(0)
            return sink, count
        except BaseException:
            sink.close()
            raise

    def do_POST(self):
        if self.path != '/ipp/print':
            self.send_error(404)
            return
        version, reqid = b'\x02\x00', 1
        body_file = None
        try:
            with self.server.post_slots:
                body_file, body_size = self._read_request()
            version, op, reqid, attrs, document_offset = parse_stream(body_file)
            document_size = body_size - document_offset
            if document_size < 0:
                raise ValueError('Comprimento IPP invalido')
            body_file.seek(document_offset)
            signature = body_file.read(16)
            self._quiet_poll = op in (0x0009, 0x000A, 0x000B)
            logfn = LOG.debug if self._quiet_poll else LOG.info
            logfn('IPP %s op=0x%04X id=%s documento=%d bytes de %s',
                  version.hex(), op, reqid, document_size, self.client_address[0])
            LOG.debug('IPP atributos recebidos: %s', attrs)
            media_ipp = attrs.get('media-col', [])
            if op in (0x0002, 0x0004) and 21000 in media_ipp and 29700 in media_ipp:
                LOG.warning(
                    'O Android solicitou A4 (210x297 mm), mas a impressora usa etiquetas '
                    '110x60 mm. A requisicao IPP sera aceita para diagnostico; '
                    'confira tamanho e quantidade de paginas ANTES de usar --print.'
                )
            uri = self.server.uri
            status, groups = 0, []
            if op == 0x000B:
                requested = attrs.get('requested-attributes')
                values = printer_attrs(uri)
                if requested and not set(requested).intersection(
                        {'all', 'printer-description', 'printer-defaults', 'printer-status'}):
                    values = [value for value in values if value[1] in requested]
                (LOG.info if len(values) > 10 else LOG.debug)(
                    'Get-Printer-Attributes: %s atributos devolvidos', len(values))
                groups = [(PRINTER_GROUP, values)]
            elif op == 0x0004:
                pedido = first(attrs, 'document-format', None)
                if formato_aceito(pedido) is None:
                    status = UNSUPPORTED
                    LOG.warning('Validate-Job: formato nao aceito: %r', pedido)
                try:
                    quantidade_copias(attrs)
                except ValueError as exc:
                    status = UNSUPPORTED
                    LOG.warning('Validate-Job: %s', exc)
            elif op == 0x0002:
                declarado = first(attrs, 'document-format', None)
                mime = formato_aceito(declarado, signature)
                try:
                    copies = quantidade_copias(attrs)
                except ValueError as exc:
                    copies = None
                    LOG.warning('Print-Job rejeitado: %s', exc)
                if mime is None or copies is None:
                    status = UNSUPPORTED
                    LOG.warning('Print-Job rejeitado: formato=%r; assinatura=%r',
                                declarado, signature[:12])
                else:
                    LOG.info('Print-Job: declarado=%r, detectado=%s, copias=%d',
                             declarado, mime, copies)
                    global next_job
                    with job_lock:
                        jid = next_job
                        next_job += 1
                        job = {
                            'id': jid, 'state': 3, 'reason': 'none',
                            'name': str(first(attrs, 'job-name', 'Etiqueta'))[:100],
                            'mime': mime, 'copies': copies,
                            'pages_done': 0, 'labels_done': 0,
                        }
                    # Persistir o documento em disco evita acumular PDFs grandes na fila RAM.
                    spool_name = f'job_{jid}_{uuid.uuid4().hex}.bin'
                    spool_path = self.server.spool_dir / spool_name
                    size = document_size
                    with self.server.queue_lock:
                        has_room = self.server.queue_bytes + size <= self.server.max_queue_bytes
                        if has_room:
                            self.server.queue_bytes += size
                    if not has_room or self.server.job_queue.full():
                        if has_room:
                            with self.server.queue_lock:
                                self.server.queue_bytes -= size
                        status = 0x0507  # server-error-busy
                        LOG.warning('Fila cheia: trabalho IPP rejeitado; bytes=%d', size)
                    else:
                        try:
                            body_file.seek(document_offset)
                            with spool_path.open('wb') as destination:
                                shutil.copyfileobj(body_file, destination, HTTP_IO_CHUNK)
                            job['spool_path'] = str(spool_path)
                            job['spool_bytes'] = size
                            with job_lock:
                                # Historico limitado. Mantem trabalhos pendentes/ativos.
                                if len(jobs) >= MAX_HISTORY:
                                    finals = [j for j in jobs if jobs[j]['state'] in (7, 8, 9)]
                                    for old in finals[:max(1, len(jobs) - MAX_HISTORY + 1)]:
                                        jobs.pop(old, None)
                                jobs[jid] = job
                            self.server.job_queue.put_nowait(jid)
                            groups = [(JOB, job_attrs(job, uri))]
                            LOG.info('Print-Job ACEITO na fila: id=%d bytes=%d copias=%d', jid, size, copies)
                        except (OSError, queue.Full):
                            spool_path.unlink(missing_ok=True)
                            with job_lock:
                                jobs.pop(jid, None)
                            with self.server.queue_lock:
                                self.server.queue_bytes -= size
                            status = 0x0507  # server-error-busy
                            LOG.exception('Nao foi possivel enfileirar trabalho %d', jid)
            elif op in (0x0009, 0x000A):
                if op == 0x0009:  # Get-Job-Attributes: inclui historico
                    jid = first(attrs, 'job-id', -1)
                    with job_lock:
                        selected = [jobs[jid].copy()] if jid in jobs else []
                    if not selected:
                        status = NOT_FOUND
                        LOG.debug('Get-Job-Attributes: job-id=%s nao encontrado', jid)
                    else:
                        LOG.debug('Get-Job-Attributes: job-id=%s estado=%s razao=%s',
                                  jid, selected[0]['state'], selected[0]['reason'])
                else:  # Get-Jobs: por padrao apenas trabalhos em andamento (RFC 8011)
                    which = first(attrs, 'which-jobs', 'not-completed')
                    if which not in ('not-completed', 'completed'):
                        status = UNSUPPORTED
                        selected = []
                    else:
                        with job_lock:
                            selected = [j.copy() for j in jobs.values()
                                        if (j['state'] in (7, 8, 9)) == (which == 'completed')][-30:]
                    LOG.debug('Get-Jobs: which-jobs=%s count=%s', which, len(selected))
                groups = [(JOB, job_attrs(job, uri)) for job in selected]
            elif op == 0x0008:
                jid = first(attrs, 'job-id', -1)
                with job_lock:
                    job = jobs.get(jid)
                    if job is None:
                        status = NOT_FOUND
                    elif job['state'] not in (7, 8, 9):
                        # Limitacao: nao e possivel remover bytes ja enviados ao spooler.
                        job['state'], job['reason'] = 7, 'job-canceled-by-user'
            else:
                status = UNSUPPORTED
            (LOG.debug if status == 0 and getattr(self, '_quiet_poll', False)
             else LOG.info)('Resposta IPP: status=0x%04X, grupos=%d', status, len(groups))
            out = response(version, status, reqid, groups)
        except OverflowError as exc:
            LOG.warning('%s', exc)
            self.send_error(413, str(exc))
            self.close_connection = True
            return
        except (ValueError, struct.error) as exc:
            LOG.warning('Requisicao IPP invalida: %s', exc)
            out = response(version, BAD_REQUEST, reqid)
        except Exception:
            LOG.exception('Falha inesperada na requisicao IPP')
            out = response(version, 0x0500, reqid)
        self.send_response(200)
        self.send_header('Content-Type', 'application/ipp')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        try:
            self.wfile.write(out)
        finally:
            if body_file is not None:
                body_file.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8631)
    parser.add_argument('--ip', required=True, help='IPv4 LAN do computador')
    parser.add_argument('--printer', default=PRINTER)
    parser.add_argument('--preview-dir', type=Path, default=Path(__file__).resolve().parent / 'previews_ipp')
    parser.add_argument('--no-mdns', action='store_true')
    parser.add_argument('--mdns-name', default='Zebra ZD220 IPP Multiformato',
                        help='Nome visivel no anuncio mDNS; permite testar descoberta sem cache antigo')
    parser.add_argument('--print', action='store_true', help='Habilita a impressao REAL')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--max-queue-jobs', type=int, default=MAX_QUEUE_JOBS,
                        help='Maximo de trabalhos aguardando processamento (padrao 8)')
    parser.add_argument('--max-queue-mib', type=int, default=400,
                        help='Limite de documentos em disco, MiB (padrao 400)')
    parser.add_argument('--spool-batch-labels', type=int, default=16,
                        help='Etiquetas por envio RAW ao Windows (padrao 16; 1 desativa)')
    parser.add_argument('--spool-batch-mib', type=int, default=2,
                        help='Tamanho maximo aproximado de cada envio RAW, MiB')
    parser.add_argument('--zpl-compression', choices=['hex', 'z64'], default='hex',
                        help='hex: compatibilidade maxima (padrao); z64: compressao experimental firmware')
    parser.add_argument('--copies-strategy', choices=['repeat', 'zpl'], default='repeat',
                        help='repeat: replica ZPL (padrao); zpl: ^PQ copias pela impressora (experimental)')
    parser.add_argument('--save-print-previews', action='store_true',
                        help='Salva PNG+ZPL de cada pagina tambem ao imprimir fisicamente')

    parser.add_argument('--max-pdf-pages', type=int, default=MAX_PDF_PAGES,
                        help='Maximo de paginas PDF por trabalho (padrao 500; maximo 5000).')
    parser.add_argument('--max-labels-per-job', type=int, default=MAX_LABELS_PER_JOB,
                        help='Maximo total de etiquetas por trabalho: paginas x copias (padrao 1000).')
    parser.add_argument('--layout-mode', choices=('smart', 'legacy'), default='smart',
                        help='smart: recorta no PDF e renderiza direto; legacy: transformacoes anteriores')
    parser.add_argument('--content-orientation',
                        choices=('auto', 'preserve', 'clockwise', 'counterclockwise'),
                        default='auto',
                        help='Orientacao do conteudo: auto usa a proporcao real, nao a pagina A4')
    parser.add_argument('--trim-threshold', type=int, default=245,
                        help='Pixels abaixo deste nivel definem a area ocupada (0..255)')
    parser.add_argument('--render-factor', type=float, default=2.0,
                        help='Supersampling da regiao PDF antes da reducao para 203 dpi (1..3)')
    parser.add_argument('--binarization', choices=('fixed', 'otsu'), default='fixed',
                        help='fixed preserva comportamento anterior; otsu ajusta contraste automaticamente')
    parser.add_argument('--align-x', choices=('left', 'center', 'right'), default='center',
                        help='Alinhamento horizontal do conteudo no raster ZPL (smart)')
    parser.add_argument('--align-y', choices=('top', 'center', 'bottom'), default='center',
                        help='Alinhamento no sentido do avanco do papel (smart)')
    parser.add_argument('--rotation', type=int, choices=(0, 90, 180, 270), default=0,
                        help='Rotacao extra (graus anti-horarios). 0=nenhuma; perfil driver ^PW480/^LL879.')
    parser.add_argument('--crop-margin', type=int, default=12,
                        help='Margem ao ampliar o conteudo dentro do raster original')
    parser.add_argument('--safe-margin', type=int, default=0,
                        help='Margem extra em pixels no raster ZPL de 480x879')
    parser.add_argument('--threshold', type=int, default=180,
                        help='Limiar preto/branco 0..255; padrao 180')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Escala relativa, entre 0.2 e 1.0; padrao 1.0')
    parser.add_argument('--offset-x', type=int, default=0, help='Deslocar para a direita (dots)')
    parser.add_argument('--offset-y', type=int, default=0, help='Deslocar para baixo (dots)')
    parser.add_argument('--no-crop', action='store_true', help='Nao recortar margens brancas do PDF')
    parser.add_argument('--test-pdf', type=Path, help='Processar PDF local SEM imprimir e SEM iniciar IPP')
    parser.add_argument('--test-file', type=Path, help='Processar PDF/JPEG/PNG local SEM imprimir e SEM iniciar IPP')
    parser.add_argument('--calibrate', action='store_true',
                        help='Gerar padrao de calibracao; so imprime se usar tambem --print')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    if not 1 <= args.max_queue_jobs <= 64:
        parser.error('--max-queue-jobs deve ficar entre 1 e 64')
    if not 100 <= args.max_queue_mib <= 4096:
        parser.error('--max-queue-mib deve ficar entre 100 e 4096')
    if not 1 <= args.spool_batch_labels <= 128:
        parser.error('--spool-batch-labels deve ficar entre 1 e 128')
    if not 1 <= args.spool_batch_mib <= 16:
        parser.error('--spool-batch-mib deve ficar entre 1 e 16')
    if not 1 <= args.max_pdf_pages <= HARD_MAX_PDF_PAGES:
        parser.error(f'--max-pdf-pages deve estar entre 1 e {HARD_MAX_PDF_PAGES}')
    if not 1 <= args.max_labels_per_job <= HARD_MAX_LABELS_PER_JOB:
        parser.error(f'--max-labels-per-job deve estar entre 1 e {HARD_MAX_LABELS_PER_JOB}')
    if not args.mdns_name.strip() or len(args.mdns_name.encode('utf-8')) > 63 or '.' in args.mdns_name:
        parser.error('--mdns-name: nome nao vazio, maximo 63 bytes, sem ponto')
    if not (0 <= args.crop_margin <= 100):
        parser.error('--crop-margin deve estar entre 0 e 100')
    if not (0 <= args.safe_margin <= 100):
        parser.error('--safe-margin deve estar entre 0 e 100')
    if not (0.2 <= args.scale <= 1.0):
        parser.error('--scale deve estar entre 0.2 e 1.0')
    if not (0 <= args.threshold <= 255):
        parser.error('--threshold deve estar entre 0 e 255')
    if not (0 <= args.trim_threshold <= 255):
        parser.error('--trim-threshold deve estar entre 0 e 255')
    if not (1.0 <= args.render_factor <= 3.0):
        parser.error('--render-factor deve estar entre 1.0 e 3.0')

    # Servico local de testes: sem rede, sem Android, sem envio fisico nao autorizado.
    if args.test_pdf or args.test_file:
        caminho_teste = args.test_file or args.test_pdf
        if not caminho_teste.is_file():
            parser.error(f'Arquivo nao encontrado: {caminho_teste}')
        import types
        config = types.SimpleNamespace(
            rotation=args.rotation, crop_margin=args.crop_margin,
            safe_margin=args.safe_margin, offset_x=args.offset_x,
            offset_y=args.offset_y, scale=args.scale, threshold=args.threshold,
            auto_crop=not args.no_crop,
            layout_mode=args.layout_mode, content_orientation=args.content_orientation,
            align_x=args.align_x, align_y=args.align_y,
            trim_threshold=args.trim_threshold, render_factor=args.render_factor,
            binarization=args.binarization,
            max_pdf_pages=args.max_pdf_pages,
            max_labels_per_job=args.max_labels_per_job,
            preview_dir=args.preview_dir,
            spool_batch_labels=args.spool_batch_labels,
            spool_batch_bytes=args.spool_batch_mib * 1024 * 1024,
            copies_strategy=args.copies_strategy,
            zpl_compression=args.zpl_compression,
            save_print_previews=args.save_print_previews,
        )
        dados_teste = caminho_teste.read_bytes()
        mime_teste = detectar_formato(dados_teste)
        if mime_teste is None or (args.test_pdf and mime_teste != 'application/pdf'):
            parser.error('Arquivo local nao e PDF/JPEG/PNG valido')
        processar_documento(dados_teste, mime_teste, server=config,
                            jid='local', print_real=False)
        LOG.info('Teste local concluido: nenhuma impressao fisica')
        return

    if args.calibrate:
        # CORRECAO: o modo --calibrate agora respeita --rotation,
        # --scale, --safe-margin e --offset-x/--offset-y.
        raster = preparar_imagem_zpl(
            raster_calibracao(),
            rotation=args.rotation,
            crop_margin=args.crop_margin,
            safe_margin=args.safe_margin,
            offset_x=args.offset_x,
            offset_y=args.offset_y,
            scale=args.scale,
            auto_crop=False,
        )
        raster = raster_preto_branco(raster, threshold=args.threshold, mode=args.binarization)
        zpl = codificar_zpl(raster, compression=args.zpl_compression)
        caminho_png, caminho_zpl = salvar_artefatos(
            args.preview_dir, f'calibracao_rot{args.rotation}', raster, zpl
        )
        LOG.info('Calibracao rotacao=%d: PNG=%s ZPL=%s',
                 args.rotation, caminho_png, caminho_zpl)
        if args.print:
            send_raw(zpl, args.printer)
            LOG.info('Calibracao enviada ao spooler (impressao real habilitada)')
        else:
            LOG.info('Calibracao gerada SEM imprimir; acrescente --print apenas se desejar')
        return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.uri = f'ipp://{args.ip}:{args.port}/ipp/print'
    server.printer = args.printer
    server.dry_run = not args.print
    server.preview_dir = args.preview_dir
    server.preview_dir.mkdir(parents=True, exist_ok=True)
    server.rotation = args.rotation
    server.layout_mode = args.layout_mode
    server.content_orientation = args.content_orientation
    server.align_x = args.align_x
    server.align_y = args.align_y
    server.trim_threshold = args.trim_threshold
    server.render_factor = args.render_factor
    server.binarization = args.binarization
    server.crop_margin = args.crop_margin
    server.safe_margin = args.safe_margin
    server.scale = args.scale
    server.threshold = args.threshold
    server.offset_x = args.offset_x
    server.offset_y = args.offset_y
    server.auto_crop = not args.no_crop
    server.max_pdf_pages = args.max_pdf_pages
    server.max_labels_per_job = args.max_labels_per_job
    server.spool_dir = Path(__file__).resolve().parent / 'spool_ipp'
    server.spool_dir.mkdir(parents=True, exist_ok=True)
    server.job_queue = queue.Queue(maxsize=args.max_queue_jobs)
    server.queue_lock = threading.Lock()
    server.queue_bytes = 0
    server.max_queue_bytes = args.max_queue_mib * 1024 * 1024
    server.post_slots = threading.BoundedSemaphore(3)
    server.spool_batch_labels = args.spool_batch_labels
    server.spool_batch_bytes = args.spool_batch_mib * 1024 * 1024
    server.copies_strategy = args.copies_strategy
    server.zpl_compression = args.zpl_compression
    server.save_print_previews = args.save_print_previews
    worker = threading.Thread(target=worker_de_impressao, args=(server,), daemon=True,
                              name='zebra-print-worker')
    worker.start()
    LOG.info('Otimizacao: worker unico + fila ate %d trabalhos/%d MiB; batch ate %d etiquetas/%d MiB',
             args.max_queue_jobs, args.max_queue_mib, args.spool_batch_labels, args.spool_batch_mib)
    LOG.info('Limite HTTP: %d MiB; midia: %s', MAX_REQUEST // (1024 * 1024), MEDIA)
    LOG.info('Lotes: maximo %d paginas PDF e %d etiquetas por trabalho; %d copias por pagina',
             args.max_pdf_pages, args.max_labels_per_job, MAX_COPIES)
    LOG.info('Modo: %s', 'IMPRESSAO REAL' if args.print else 'PREVIA (nao imprime)')
    LOG.info('Raster final: %dx%d; rotation=%d; escala=%.2f; offset=(%d,%d)',
             ZPL_WIDTH, ZPL_LENGTH, args.rotation, args.scale, args.offset_x, args.offset_y)

    zeroconf = None
    if not args.no_mdns:
        try:
            from zeroconf import Zeroconf, ServiceInfo
            zeroconf = Zeroconf()
            # Anuncio DNS-SD de IPP GENERICO. Nao anunciar AirPrint/IPP Everywhere:
            # a ponte oferece PDF/JPEG/PNG; nao oferece PWG Raster, PCLm nem URF.
            # UUID deve ser o mesmo da propriedade IPP printer-uuid, mas sem urn:uuid:.
            mdns_name = args.mdns_name.strip()
            properties = {
                b'txtvers': b'1',
                b'qtotal': b'1',
                b'rp': b'ipp/print',
                b'ty': b'Zebra ZD220 IPP Etiquetas',
                b'product': b'(Zebra ZD220)',
                b'pdl': ','.join(SUPPORTED_DOCUMENT_FORMATS).encode('ascii'),
                b'UUID': PRINTER_UUID.removeprefix('urn:uuid:').encode('ascii'),
                b'note': b'Zebra ZD220 USB via Windows 11 - ponte IPP PDF/JPEG/PNG',
                b'Color': b'F',
                b'Copies': b'1',
                b'Duplex': b'F',
                # Bonjour Printing: PaperMax aceita classes predefinidas, nao medidas livres.
                # A ZD220 usa etiquetas menores que A4/Legal.
                b'PaperMax': b'<legal-A4',
                # A ponte imprime etiquetas, nao folhas, envelopes ou fotografias.
                b'kind': b'label',
                b'priority': b'50',
                b'adminurl': f'http://{args.ip}:{args.port}/'.encode('ascii'),
            }
            info = ServiceInfo(
                '_ipp._tcp.local.', f'{mdns_name}._ipp._tcp.local.',
                addresses=[socket.inet_aton(args.ip)], port=args.port,
                properties=properties, server='zebra-ipp.local.',
            )
            zeroconf.register_service(info)
            LOG.info('mDNS anunciado: %s._ipp._tcp.local. -> %s:%d/ipp/print',
                     mdns_name, args.ip, args.port)
            LOG.info('mDNS TXT: %s', {k.decode('ascii'): v.decode('utf-8')
                                      for k, v in properties.items()})
        except Exception:
            LOG.exception('Falha no mDNS; acesso IPP direto ainda disponivel')

    LOG.info('Servidor em %s; formatos=%s. CTRL+C para encerrar.',
             server.uri, ','.join(SUPPORTED_DOCUMENT_FORMATS))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # O worker eh daemon para evitar bloqueio indefinido durante shutdown.
        # Trabalhos pendentes sao marcados como incompletos se o processo for encerrado.
        if zeroconf:
            zeroconf.close()


if __name__ == '__main__':
    main()
