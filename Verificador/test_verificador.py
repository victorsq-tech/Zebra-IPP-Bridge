"""Testes locais: não imprimem, não mudam firewall e não requerem Zebra."""
import http.server
import json
import socket
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import verificador_zebra as v

class FakeIPP(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        data = b'Zebra IPP bridge online. Endpoint: /ipp/print\n'
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        size = int(self.headers['Content-Length'])
        payload = self.rfile.read(size)
        assert payload[2:4] == b'\x00\x0b', 'Not a Get-Printer-Attributes operation'
        rid = struct.unpack_from('>I', payload, 4)[0]
        # Response group with printer name and a document format.
        data = (b'\x02\x00' + struct.pack('>HI', 0, rid) + b'\x01' +
                v._val(0x47, 'attributes-charset', b'utf-8') +
                v._val(0x48, 'attributes-natural-language', b'en') +
                b'\x04' + v._val(0x42, 'printer-name', b'Zebra ZD220 Teste') +
                v._val(0x49, 'document-format-supported', b'application/pdf') + b'\x03')
        self.send_response(200)
        self.send_header('Content-Type', 'application/ipp')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeIPP)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_tcp_http_ipp(self):
        self.assertTrue(v.check_tcp('127.0.0.1', self.port)[0])
        self.assertTrue(v.check_http('127.0.0.1', self.port)[0])
        ok, desc, parsed = v.check_ipp('127.0.0.1', self.port, '/ipp/print')
        self.assertTrue(ok, desc)
        self.assertEqual(parsed['attributes']['printer-name'], ['Zebra ZD220 Teste'])

    def test_bad_request_id_is_rejected(self):
        payload = b'\x02\x00' + struct.pack('>HI', 0, 555) + b'\x03'
        with self.assertRaisesRegex(ValueError, 'Request-ID'):
            v.parse_ipp_response(payload, 127)

    def test_report_does_not_print(self):
        report = v.run_checks('127.0.0.1', self.port, windows=False, mdns=False, timeout=0.2)
        self.assertEqual(report['overall'] in ('OK', 'AVISO'), True)
        names = [x['name'] for x in report['checks']]
        self.assertIn('IPP Get-Printer-Attributes', names)
        self.assertIn('DNS-SD _ipp._tcp', names)
        with TemporaryDirectory() as d:
            txt, js = v.save_report(report, d)
            self.assertTrue(txt.exists() and js.exists())
            self.assertEqual(json.loads(js.read_text('utf-8'))['endpoint'], report['endpoint'])
            self.assertIn('NÃO envia trabalhos', txt.read_text('utf-8'))

    def test_no_tcp(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        p = s.getsockname()[1]
        s.close()
        yes, _ = v.check_tcp('127.0.0.1', p, timeout=0.2)
        self.assertFalse(yes)

if __name__ == '__main__':
    unittest.main(verbosity=2)
