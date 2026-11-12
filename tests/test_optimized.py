"""Functional + performance verification without physical Zebra or zeroconf."""
from __future__ import annotations
import sys, importlib.util, types, tempfile, time, random, threading, http.client, struct, zlib
from pathlib import Path
from PIL import Image, ImageOps
import pymupdf

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from zebra_fast_engine import encode_gfa, monochrome_image, PROFILE, SpoolBatch

# Fake vendor module preserves test independence from Windows USB.
stub = types.ModuleType('print_pdf_zebra')
stub.PRINTER = 'ZDesigner ZD220-203dpi ZPL'
def render_page(page):
    pix=page.get_pixmap(matrix=pymupdf.Matrix(1.0,1.0), colorspace=pymupdf.csGRAY,alpha=False)
    img=Image.frombytes('L',(pix.width,pix.height),pix.samples)
    img=ImageOps.contain(img,(480,832))
    canvas=Image.new('L',(480,832),255)
    canvas.paste(img,((480-img.width)//2,(832-img.height)//2))
    return canvas
stub.render_page = render_page
sent=[]
stub.send_raw=lambda zpl, printer: (sent.append(zpl),len(sent))[1]
sys.modules[stub.__name__]=stub
spec = importlib.util.spec_from_file_location('ipp_optimized', HERE / 'ipp_server.py')
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)

# Bitwise parity against Python per-pixel legacy loop.
rng = random.Random(203)
image=Image.frombytes('L',(480,879),rng.randbytes(480*879))
threshold=180
start=time.perf_counter()
raw = bytearray()
for y in range(image.height):
    for x0 in range(0,image.width,8):
        byte=0
        for bit in range(8):
            if image.getpixel((x0+bit,y)) < threshold:
                byte |= 1 << (7-bit)
        raw.append(byte)
slow=time.perf_counter()-start
start=time.perf_counter()
fast_zpl=encode_gfa(image)
fast=time.perf_counter()-start
payload = bytes.fromhex(fast_zpl.split(b'^GFA,52740,52740,60,',1)[1].split(b'^FS',1)[0].decode())
assert payload == bytes(raw), '1-bit mismatch in fast ZPL encoder'
assert b'^PW480' in fast_zpl and b'^LL879' in fast_zpl
print(f'ENCODER: EXACT bitwise match, slow={slow:.4f}s fast={fast:.4f}s speedup={slow/max(fast,1e-9):.1f}x, ZPL={len(fast_zpl)} bytes')

# Batch + labels vs spool jobs
batch = SpoolBatch(stub.send_raw, 'MockZebra',max_labels=16,max_bytes=2*1024*1024)
sent.clear()
for i in range(48): batch.add(fast_zpl)
batch.flush()
assert len(sent)==3 and batch.submitted==48
print('BATCH: 48 labels in 3 Windows RAW submissions (simulated)')

# IPP end-to-end: responds before worker processes a 3-page job, worker produces 1 RAW batch.
with tempfile.TemporaryDirectory() as tmp:
    server = mod.ThreadingHTTPServer(('127.0.0.1',0), mod.Handler)
    server.uri=f'ipp://127.0.0.1:{server.server_port}/ipp/print'
    server.printer='MockZebra';server.dry_run=False
    server.preview_dir=Path(tmp)/'previews';server.preview_dir.mkdir()
    server.spool_dir=Path(tmp)/'spool';server.spool_dir.mkdir()
    server.rotation=0;server.crop_margin=12;server.safe_margin=0
    server.scale=1;server.threshold=180;server.offset_x=0;server.offset_y=0;server.auto_crop=True
    server.max_pdf_pages=500;server.max_labels_per_job=1000
    server.spool_batch_labels=16;server.spool_batch_bytes=2*1024*1024
    server.copies_strategy='repeat';server.save_print_previews=False
    server.job_queue=mod.queue.Queue(maxsize=8)
    server.queue_lock=threading.Lock();server.queue_bytes=0;server.max_queue_bytes=400*1024*1024
    server.post_slots=threading.BoundedSemaphore(3)
    worker=threading.Thread(target=mod.worker_de_impressao,args=(server,),daemon=True);worker.start()
    th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
    pdf=pymupdf.open()
    for i in range(3):
        page=pdf.new_page(width=311.8,height=170.0);page.insert_text((32,65),f'ETIQUETA {i+1}')
    payload=pdf.tobytes(); pdf.close()
    def req(op,reqid,doc=b'',job_id=None,copies=1):
        opattrs = mod.group(mod.OP,[(mod.CHARSET,'attributes-charset','utf-8'),(mod.LANG,'attributes-natural-language','en'),(mod.URI,'printer-uri',server.uri),(mod.MIME,'document-format','application/pdf')])
        jobattrs = mod.group(mod.JOB,[(mod.INTEGER,'job-id',job_id)] if job_id else [(mod.INTEGER,'copies',copies)]) if op==0x0002 else b''
        return b'\x02\x00'+struct.pack('>HI',op,reqid)+opattrs+jobattrs+bytes([mod.END])+doc
    def post(data):
        c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20)
        c.request('POST','/ipp/print',body=data,headers={'Content-Type':'application/ipp'})
        r=c.getresponse();result=r.read();status=r.status;c.close()
        return status,result
    try:
        sent.clear()
        status,attrs=post(req(0x000B,98))
        assert status==200 and attrs[:4] == b'\x02\x00\x00\x00'
        t0=time.perf_counter()
        status,returned=post(req(0x0002,99,payload,copies=3))
        response_time=time.perf_counter()-t0
        assert status==200 and returned[:4]==b'\x02\x00\x00\x00', returned[:12].hex()
        assert response_time < 3, response_time
        with mod.job_lock:
            jid=max(mod.jobs)
        server.job_queue.join()
        with mod.job_lock: state=mod.jobs[jid]['state']
        assert state==9, (jid,state)
        assert len(sent)==1 and sent[0].count(b'^XA')==9 and sent[0].count(b'^XZ')==9, (len(sent), sent[0].count(b'^XA'))
        assert server.queue_bytes == 0 and not list(server.spool_dir.iterdir())
        print(f'IPP TCP: queued 3 PDF pages x 3 copies = 9 labels, HTTP 200 in {response_time:.3f}s, worker completed state={state}, 1 RAW job')
        # optional zpl copies mode
        sent.clear();server.copies_strategy='zpl'
        status,returned=post(req(0x0002,100,payload,copies=3))
        server.job_queue.join()
        assert len(sent)==1 and sent[0].count(b'^PQ3')==3
        print('ZPL ^PQ: optional printer-side repeats injected on 3 pages (no hardware validation)')
    finally:
        server.shutdown();server.server_close()
print('ALL TESTS PASSED')
