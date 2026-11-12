"""Testes de formatacao sem dispositivo Zebra e sem IPP ao vivo."""
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import sys
import importlib.util
from PIL import Image, ImageDraw
import pymupdf

HERE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HERE))
from zebra_formatter import LayoutOptions, format_pdf_page, format_source_image, binarize
from zebra_fast_engine import encode_gfa, ZebraProfile

# Referencia de modulo Windows do projeto, substituida somente neste teste.
stub=types.ModuleType('print_pdf_zebra')
stub.PRINTER='ZDesigner ZD220-203dpi ZPL'
stub.send_raw=lambda zpl,printer: 1
stub.render_page=lambda page: Image.new('L',(480,832),255)
sys.modules['print_pdf_zebra']=stub
spec=importlib.util.spec_from_file_location('ipp_format_test',HERE/'ipp_server.py')
server=importlib.util.module_from_spec(spec);sys.modules[spec.name]=server;spec.loader.exec_module(server)


def ink_bounds(im):
    return im.point(lambda x: 255 if x < 240 else 0).getbbox()

with TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    # O Android pode montar PDF A4 com uma etiqueta pequena no centro.
    a4=pymupdf.open()
    page=a4.new_page(width=595,height=842)
    page.draw_rect(pymupdf.Rect(200,340,400,470),color=(0,0,0),width=1)
    page.insert_text((225,375),'LOTE 12345  -  TESTE',fontsize=15)
    for i in range(45):
        if i%3 != 0:
            x=214+i*3.5
            page.draw_line((x,400),(x,450),color=(0,0,0),width=1.8)
    page=a4[0]
    opts=LayoutOptions()
    raster,info=format_pdf_page(page,opts)
    assert raster.size==(480,879)
    assert info.orientation=='clockwise',info
    assert info.bbox_source[0]>150 and info.bbox_source[1]>300, info
    assert ink_bounds(raster) is not None
    assert info.position[0]>=0 and info.position[1]>=0 and not info.clipped
    preview,thr=binarize(raster,mode='fixed',threshold=180)
    zpl=encode_gfa(preview,profile=ZebraProfile(width=480,length=879))
    bitmap = bytes.fromhex(zpl.split(b'^GFA,52740,52740,60,',1)[1].split(b'^FS',1)[0].decode())
    # O bitmap da previa exata ao ZPL foi empacotado invertendo os bits 1/0.
    assert bitmap == bytes(~v & 0xff for v in preview.convert('1').tobytes())
    preview.save(tmp/'a4_etiqueta_formatada.png')
    print('A4: origem=',info.bbox_source,'posicao=',info.position,'conteudo=',info.content_size,'ZPL=',len(zpl))

    # Documento original em 110 x 60 mm horizontal (proporcao paisagem).
    horizontal=pymupdf.open()
    p=horizontal.new_page(width=311.81,height=170.08)
    p.draw_rect(pymupdf.Rect(15,15,295,150),color=(0,0,0),width=2)
    p.insert_text((35,70),'ETIQUETA HORIZONTAL',fontsize=18)
    r,meta=format_pdf_page(p,opts)
    assert r.size==(480,879) and meta.orientation=='clockwise'
    assert not meta.clipped
    r.save(tmp/'horizontal_formatada.png')
    print('PDF HORIZONTAL:',meta.to_dict())

    # Imagem horizontal, preservar transparencia branca e preencher corretamente.
    im=Image.new('RGBA',(2000,900),(255,255,255,0))
    draw=ImageDraw.Draw(im)
    draw.text((100,100),'ETIQUETA IMAGEM',fill=(0,0,0,255))
    draw.rectangle((100,200,1900,700),outline=(0,0,0,255),width=8)
    white=Image.new('RGBA',im.size,'white');white.alpha_composite(im)
    result,meta=format_source_image(white.convert('RGB'),opts)
    assert result.size==(480,879) and meta.orientation=='clockwise'
    assert not meta.clipped
    result.save(tmp/'imagem_formatada.png')

    # Deslocamento que ultrapassaria o papel deve ser sinalizado.
    out,meta=format_source_image(white.convert('RGB'),LayoutOptions(offset_x=400))
    assert meta.clipped
    # Variantes manuais devem produzir orientacoes diferentes.
    rots=[]
    for rot in (0,90,180,270):
        r,_=format_source_image(white.convert('RGB'),LayoutOptions(rotation=rot))
        rots.append(r.tobytes())
    assert len(set(rots)) == 4

    # O PDF completo de 2 paginas e formatos diferentes devem sobreviver ao servidor.
    sample=tmp/'duas_paginas.pdf'
    pages=pymupdf.open()
    for n in (1, 2):
        item=pages.new_page(width=311.8, height=170.0)
        item.insert_text((20, 60), f'ETIQUETA {n}', fontsize=22)
    pages.save(sample)
    pages.close()
    import types
    cfg=types.SimpleNamespace(rotation=0, crop_margin=12,safe_margin=0,
                              offset_x=0,offset_y=0,scale=1.0, threshold=180,
                              auto_crop=True,layout_mode='smart',content_orientation='auto',
                              trim_threshold=245,render_factor=2.0,binarization='fixed',
                              max_pdf_pages=500,max_labels_per_job=1000,
                              preview_dir=tmp/'outputs',spool_batch_labels=8,
                              spool_batch_bytes=2*1024*1024,copies_strategy='repeat',
                              zpl_compression='hex',save_print_previews=False)
    server.processar_documento(sample,'application/pdf',server=cfg,jid='local',print_real=False)
    assert len(list((tmp/'outputs').glob('*.png'))) == 2
    assert len(list((tmp/'outputs').glob('*.zpl'))) == 2
    print('2 PAGINAS: duas previas e dois ZPLs gerados')

    # Nao perder codigo de barras preto / nao gerar branco com bit preto.
    blank=Image.new('L',(480,879),'white')
    zero=encode_gfa(blank)
    assert b'^GFA,52740,52740,60,' in zero and zero.count(b'FF') < 5

print('TESTES DE FORMATACAO APROVADOS')
