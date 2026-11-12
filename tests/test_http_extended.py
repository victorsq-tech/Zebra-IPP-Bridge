import sys, importlib.util, types, threading, http.client, struct, tempfile, io
from pathlib import Path
from PIL import Image
import pymupdf

HERE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HERE))
stub = types.ModuleType('print_pdf_zebra')
stub.PRINTER='MOCK'
stub.render_page=lambda page: Image.new('L',(480,832),255)
sent=[]
stub.send_raw=lambda zpl,printer: (sent.append(zpl), len(sent))[1]
sys.modules[stub.__name__]=stub
spec=importlib.util.spec_from_file_location('ipp_optimized_extend',HERE/'ipp_server.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

def request(oper,reqid,doc=b'',mime='application/pdf',copies=1):
    attrs=m.group(m.OP,[(m.CHARSET,'attributes-charset','utf-8'),(m.LANG,'attributes-natural-language','en'),(m.URI,'printer-uri',server.uri),(m.MIME,'document-format',mime)])
    jobattrs=m.group(m.JOB,[(m.INTEGER,'copies',copies)]) if oper==0x0002 else b''
    return b'\x02\x00'+struct.pack('>HI',oper,reqid)+attrs+jobattrs+bytes([m.END])+doc

def post(data, chunked=False):
    c=http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
    if chunked:
        body=[data[:13],data[13:257],data[257:]]
        c.request('POST','/ipp/print',body=body,headers={'Content-Type':'application/ipp'},encode_chunked=True)
    else:
        c.request('POST','/ipp/print',body=data,headers={'Content-Type':'application/ipp'})
    res=c.getresponse();d=res.read();status=res.status;c.close()
    return status,d

with tempfile.TemporaryDirectory() as tmp:
    server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
    server.uri=f'ipp://127.0.0.1:{server.server_port}/ipp/print';server.printer='MOCK';server.dry_run=False
    server.spool_dir=Path(tmp)/'spool';server.spool_dir.mkdir();server.preview_dir=Path(tmp)/'preview';server.preview_dir.mkdir()
    server.rotation=0;server.crop_margin=12;server.safe_margin=0;server.scale=1;server.threshold=180
    server.offset_x=0;server.offset_y=0;server.auto_crop=True
    server.max_pdf_pages=500;server.max_labels_per_job=1000;server.spool_batch_labels=16;server.spool_batch_bytes=2*1024*1024
    server.copies_strategy='repeat';server.save_print_previews=False
    server.job_queue=m.queue.Queue(maxsize=8);server.queue_lock=threading.Lock();server.queue_bytes=0
    server.max_queue_bytes=400*1024*1024;server.post_slots=threading.BoundedSemaphore(3)
    worker=threading.Thread(target=m.worker_de_impressao,args=(server,),daemon=True);worker.start()
    http_thread=threading.Thread(target=server.serve_forever,daemon=True);http_thread.start()
    try:
        img=Image.new('RGBA',(720,400),(255,255,255,0))
        img.putpixel((30,25),(0,0,0,255))
        b=io.BytesIO();img.save(b,'PNG');png=b.getvalue()
        status,response=post(request(0x0002,100,png,'image/png',3),chunked=True)
        assert status==200 and response[:4]==b'\x02\x00\x00\x00'
        server.job_queue.join()
        assert len(sent)==1 and sent[0].count(b'^XZ')==3
        print('HTTP CHUNKED: PNG transparent -> queued -> ZPL 3 copies in 1 RAW batch')
        sent.clear()
        rgb=Image.new('RGB',(600,320),'white');rgb.putpixel((10,10),(0,0,0))
        b=io.BytesIO();rgb.save(b,'JPEG');jpeg=b.getvalue()
        status,response=post(request(0x0002,101,jpeg,'image/jpeg',2))
        assert status==200 and response[:4]==b'\x02\x00\x00\x00'
        server.job_queue.join()
        assert len(sent)==1 and sent[0].count(b'^XZ')==2
        print('HTTP Content-Length: JPEG -> queued -> 2 copies in 1 RAW batch')
        assert not list(server.spool_dir.glob('*'))
        assert not list(server.preview_dir.glob('*'))
    finally:
        server.shutdown();server.server_close()
print('EXTENDED TESTS PASSED')
