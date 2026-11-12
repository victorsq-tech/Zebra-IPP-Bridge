"""Diagnostico local, SEM rede, SEM envio para a Zebra.

Execute na pasta C:\\ZebraIPP depois de copiar os tres modulos novos e conservar
seu print_pdf_zebra.py original. Este verificador usa o arquivo de exemplo.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import importlib
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def ok(s):
    print('[OK] ' + s)


def erro(s):
    print('[ERRO] ' + s)


def main():
    deps = ['PIL', 'pymupdf', 'zebra_formatter', 'zebra_fast_engine']
    for name in deps:
        try:
            importlib.import_module(name)
        except Exception as exc:
            erro(f'Modulo {name}: {exc}')
            return 2
        ok('Importacao: ' + name)

    try:
        vendor = importlib.import_module('print_pdf_zebra')
        for key in ('PRINTER', 'send_raw', 'render_page'):
            if not hasattr(vendor,key):
                raise AttributeError(key)
        ok(f'Ponte do Windows encontrada: print_pdf_zebra.py (impressora: {vendor.PRINTER})')
    except Exception as exc:
        erro('Falta print_pdf_zebra.py na mesma pasta, ou o modulo contem erro: ' + str(exc))
        return 2

    try:
        import zeroconf
        ok('zeroconf disponivel para anunciar o servico IPP')
    except ImportError:
        print('[AVISO] zeroconf nao instalado: o IPP podera funcionar, mas sem anuncio mDNS')
    if sys.platform == 'win32':
        try:
            import win32print
            ok('pywin32 disponivel para envio RAW ao spooler do Windows')
        except ImportError:
            print('[AVISO] pywin32 nao instalado: impressao REAL nao funcionara')

    try:
        server = importlib.import_module('ipp_server')
        from PIL import Image
        import pymupdf
        from zebra_formatter import LayoutOptions, format_pdf_page, binarize
        from zebra_fast_engine import ZebraProfile, encode_gfa, SpoolBatch

        docpath = ROOT / 'examples' / 'exemplo_a4_com_etiqueta.pdf'
        if not docpath.is_file():
            raise FileNotFoundError(f'Exemplo nao encontrado: {docpath}')
        with pymupdf.open(docpath) as pdf:
            raster, info = format_pdf_page(pdf[0], LayoutOptions())
        assert raster.size == (480, 879)
        mono, threshold = binarize(raster)
        assert mono.size == (480,879)
        zpl = encode_gfa(mono, profile=ZebraProfile(480,879))
        assert b'^PW480' in zpl and b'^LL879' in zpl and b'^GFA' in zpl
        assert b'^JUS' not in zpl
        marker = b'^GFA,52740,52740,60,'
        pixels = bytes.fromhex(zpl.split(marker,1)[1].split(b'^FS',1)[0].decode('ascii'))
        assert pixels == bytes((~v)&255 for v in mono.convert('1').tobytes())
        ok('PDF -> zebra_formatter -> preto/branco -> zebra_fast_engine -> ZPL: 480x879')
        ok('Bitmap PNG corresponde exatamente aos bytes de imagem ^GFA')

        responses=[]
        batch=SpoolBatch(lambda payload, printer:(responses.append(payload),len(responses))[1],
                         'Impressora simulada',max_labels=2,max_bytes=2*1024*1024)
        for _ in range(3):
            batch.add(zpl)
        batch.flush()
        assert sum(x.count(b'^XA') for x in responses)==3
        assert len(responses)==2
        ok('SpoolBatch conecta gerador ZPL a envios RAW simulados (3 etiquetas, 2 lotes)')

        with TemporaryDirectory() as d:
            cfg=SimpleNamespace(rotation=0,crop_margin=12,safe_margin=0,offset_x=0,offset_y=0,
                scale=1.0,threshold=180,auto_crop=True,layout_mode='smart',
                content_orientation='auto',align_x='center',align_y='center',trim_threshold=245,
                render_factor=2.0,binarization='fixed',max_pdf_pages=500,
                max_labels_per_job=1000,preview_dir=Path(d),spool_batch_labels=8,
                spool_batch_bytes=2*1024*1024,copies_strategy='repeat',zpl_compression='hex',
                save_print_previews=False)
            server.processar_documento(docpath,'application/pdf',server=cfg,jid='teste',print_real=False)
            assert len(list(Path(d).glob('*.png')))==1
            assert len(list(Path(d).glob('*.zpl')))==1
            ok('Servidor usa os dois motores para gerar PNG e ZPL, SEM impressao fisica')
    except Exception as exc:
        import traceback
        traceback.print_exc()
        erro(f'Falha de integracao: {exc}')
        return 1
    print('\nINTEGRACAO VALIDADA LOCALMENTE. NENHUMA ETIQUETA FOI IMPRESSA.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
