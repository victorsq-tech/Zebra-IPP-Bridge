"""Formatacao de etiquetas com recorte em coordenadas PDF e raster unico para ZPL.

O codigo nao faz E/S de impressora. A saida e um raster L de exatamente
480 x 879 pontos, representando os mesmos pixels binarizados para ^GFA.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import logging
import math
from typing import Any

import pymupdf
from PIL import Image, ImageOps

LOG = logging.getLogger('zebra-ipp')

DEFAULT_W, DEFAULT_H = 480, 879
ROTATIONS = {
    0: None,
    90: Image.Transpose.ROTATE_90,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,
}


@dataclass(frozen=True)
class LayoutOptions:
    width: int = DEFAULT_W
    length: int = DEFAULT_H
    crop_margin: int = 12
    safe_margin: int = 0
    rotation: int = 0
    content_orientation: str = 'auto'
    scale: float = 1.0
    offset_x: int = 0
    offset_y: int = 0
    align_x: str = 'center'
    align_y: str = 'center'
    auto_crop: bool = True
    trim_threshold: int = 245
    render_factor: float = 2.0

    def validate(self):
        if self.width < 32 or self.length < 32:
            raise ValueError('Tamanho do raster invalido')
        if self.rotation not in ROTATIONS:
            raise ValueError('Rotacao invalida')
        if self.content_orientation not in ('auto', 'preserve', 'clockwise', 'counterclockwise'):
            raise ValueError('Orientacao de conteudo invalida')
        if self.align_x not in ('left', 'center', 'right') or self.align_y not in ('top', 'center', 'bottom'):
            raise ValueError('Alinhamento invalido')
        if not (0 <= self.crop_margin <= 100 and 0 <= self.safe_margin <= 100):
            raise ValueError('Margem fora do intervalo')
        if 2 * (self.crop_margin + self.safe_margin) >= min(self.width, self.length):
            raise ValueError('Margens ultrapassam o raster')
        if not (0.2 <= self.scale <= 1.0):
            raise ValueError('Escala fora do intervalo')
        if not (0 <= self.trim_threshold <= 255):
            raise ValueError('Limiar de recorte invalido')
        if not (1.0 <= self.render_factor <= 3.0):
            raise ValueError('Fator de renderizacao fora do intervalo')
        return self


@dataclass
class LayoutResult:
    source: str
    page_size: tuple[float, float] | None
    bbox_source: tuple[float, float, float, float] | None
    orientation: str
    extra_rotation: int
    content_size: tuple[int, int]
    canvas_size: tuple[int, int]
    position: tuple[int, int]
    clipped: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bbox_ink(gray: Image.Image, threshold: int):
    """Retorna a caixa de todos os pixels nao-brancos, sem perder codigos de barras finos."""
    if gray.mode != 'L':
        gray = gray.convert('L')
    mask = gray.point(lambda v: 255 if v < threshold else 0)
    return mask.getbbox()


def _orientation(img_w, img_h, mode):
    if mode == 'clockwise':
        return 'clockwise'
    if mode == 'counterclockwise':
        return 'counterclockwise'
    if mode == 'auto' and img_w > img_h * 1.08:
        return 'clockwise'
    return 'preserve'


def _rotate_content(image: Image.Image, direction: str):
    if direction == 'clockwise':
        return image.transpose(Image.Transpose.ROTATE_270)
    if direction == 'counterclockwise':
        return image.transpose(Image.Transpose.ROTATE_90)
    return image


def _compose(image: Image.Image, options: LayoutOptions, *, source,
             page_size=None, bbox_source=None, direction='preserve'):
    options.validate()
    image = _rotate_content(image, direction)
    if options.rotation:
        image = image.transpose(ROTATIONS[options.rotation])
    padding = options.crop_margin + options.safe_margin
    avail_w = options.width - 2 * padding
    avail_h = options.length - 2 * padding
    content = ImageOps.contain(image, (avail_w, avail_h), Image.Resampling.LANCZOS)
    if options.scale != 1.0:
        content = content.resize((
            max(1, round(content.width * options.scale)),
            max(1, round(content.height * options.scale)),
        ), Image.Resampling.LANCZOS)
    result = Image.new('L', (options.width, options.length), 255)
    if options.align_x == 'left':
        x = padding
    elif options.align_x == 'right':
        x = options.width - padding - content.width
    else:
        x = (options.width - content.width) // 2
    if options.align_y == 'top':
        y = padding
    elif options.align_y == 'bottom':
        y = options.length - padding - content.height
    else:
        y = (options.length - content.height) // 2
    x += options.offset_x
    y += options.offset_y
    # Pillow clips paste outside the canvas: warn explicitly if this happens.
    clipped = x < 0 or y < 0 or x + content.width > options.width or y + content.height > options.length
    if clipped:
        LOG.warning('Layout cortado: pos=%s tamanho=%s raster=%s', (x,y), content.size, result.size)
    result.paste(content, (x, y))
    result_meta = LayoutResult(
        source=source, page_size=page_size, bbox_source=bbox_source,
        orientation=direction, extra_rotation=options.rotation,
        content_size=content.size, canvas_size=result.size,
        position=(x, y), clipped=clipped,
    )
    LOG.info('LAYOUT: %s; origem=%s; conteudo=%s; pos=%s; final=%s',
             source, direction, content.size, (x, y), result.size)
    return result, result_meta


def format_pdf_page(page, options: LayoutOptions):
    """Duas passagens economicas: detectar tinta na pagina; renderizar so o clip.

    PDF A4 com etiqueta pequena: nao reamostra a pagina A4 inteira para 480x879.
    Em vez disso, usa a bbox em pontos do PDF e renderiza diretamente so ela.
    """
    options.validate()
    page_rect = page.rect
    if not options.auto_crop:
        # Sem recorte nao precisamos renderizar a pagina de sondagem.
        clip = page_rect
    else:
        # Primeira passagem: ate 950 pixels no maior eixo, apenas 1 canal.
        probe_scale = min(2.0, 950.0 / max(page_rect.width, page_rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(probe_scale, probe_scale),
                              colorspace=pymupdf.csGRAY, alpha=False)
        probe = Image.frombytes('L', (pix.width, pix.height), pix.samples)
        bbox = _bbox_ink(probe, options.trim_threshold)
        if bbox is None:
            LOG.warning('Pagina PDF sem conteudo detectavel; gerada etiqueta em branco')
            empty = Image.new('L', (options.width, options.length), 255)
            meta = LayoutResult('pdf', (page_rect.width, page_rect.height), None,
                                'preserve', options.rotation, (0, 0), empty.size,
                                (0, 0), False)
            return empty, meta
        # Proteger as bordas: acrescentar 2 pixels da imagem de sondagem.
        pad = 2
        l = max(0, bbox[0] - pad)
        t = max(0, bbox[1] - pad)
        r = min(probe.width, bbox[2] + pad)
        b = min(probe.height, bbox[3] + pad)
        # Corrigir o arredondamento da matriz via as dimensoes efetivas da sondagem.
        fx = page_rect.width / probe.width
        fy = page_rect.height / probe.height
        clip = pymupdf.Rect(page_rect.x0 + l * fx, page_rect.y0 + t * fy,
                            page_rect.x0 + r * fx, page_rect.y0 + b * fy)
        clip &= page_rect
    direction = _orientation(clip.width, clip.height, options.content_orientation)
    swap = direction in ('clockwise', 'counterclockwise')
    if options.rotation in (90, 270):
        swap = not swap
    # Dimensionar o clip *diretamente* para o raster final, com supersampling.
    inset = options.crop_margin + options.safe_margin
    usable_w = options.width - 2 * inset
    usable_h = options.length - 2 * inset
    mapped_w = clip.height if swap else clip.width
    mapped_h = clip.width if swap else clip.height
    factor = min(usable_w / max(mapped_w, 1e-6), usable_h / max(mapped_h, 1e-6))
    factor *= options.render_factor
    # Limite de memoria/CPU se o documento contiver um unico ponto minusculo.
    factor = max(0.05, min(factor, 16.0))
    high = page.get_pixmap(matrix=pymupdf.Matrix(factor, factor), clip=clip,
                           colorspace=pymupdf.csGRAY, alpha=False)
    image = Image.frombytes('L', (high.width, high.height), high.samples)
    result, meta = _compose(image, options, source='pdf',
                            page_size=(round(page_rect.width, 2), round(page_rect.height, 2)),
                            bbox_source=tuple(round(v, 3) for v in clip),
                            direction=direction)
    return result, meta


def format_source_image(image: Image.Image, options: LayoutOptions):
    options.validate()
    image = image.convert('L')
    bbox = _bbox_ink(image, options.trim_threshold) if options.auto_crop else None
    if bbox is not None:
        # Pequeno padding protege linhas/barcodes encostados nas bordas.
        l, t, r, b = bbox
        image = image.crop((max(0, l - 2), max(0, t - 2),
                            min(image.width, r + 2), min(image.height, b + 2)))
    elif options.auto_crop:
        blank = Image.new('L', (options.width, options.length), 255)
        meta = LayoutResult('image', None, None, 'preserve', options.rotation,
                            (0, 0), blank.size, (0, 0), False)
        return blank, meta
    direction = _orientation(image.width, image.height, options.content_orientation)
    return _compose(image, options, source='image', direction=direction)


def otsu_threshold(image: Image.Image, *, min_threshold=95, max_threshold=230) -> int:
    """Calcula limiar de Otsu a partir do histograma (modo L), sem dependencia extra."""
    hist = image.convert('L').histogram()
    n = sum(hist)
    if not n:
        return 180
    total = sum(i * x for i, x in enumerate(hist))
    wk, sk, best_var, selected = 0, 0, -1.0, 180
    for i, x in enumerate(hist):
        wk += x
        if wk == 0:
            continue
        w1 = n - wk
        if w1 == 0:
            break
        sk += i * x
        m0, m1 = sk / wk, (total - sk) / w1
        score = wk * w1 * (m0 - m1) ** 2
        if score > best_var:
            best_var = score
            selected = i
    return max(min_threshold, min(max_threshold, selected + 1))


def binarize(image: Image.Image, *, mode='fixed', threshold=180):
    gray = image.convert('L')
    selected = threshold if mode == 'fixed' else otsu_threshold(gray)
    if mode not in ('fixed', 'otsu'):
        raise ValueError('Modo de binarizacao invalido')
    return gray.point(lambda v: 0 if v < selected else 255), selected
