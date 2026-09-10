#!/usr/bin/env python3
"""Loopback-only, range-capable HTTP/HTTPS fixture server for adb reverse."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import ssl
import threading

parser = argparse.ArgumentParser()
parser.add_argument('root', type=Path)
parser.add_argument('--cert', required=True)
parser.add_argument('--key', required=True)
args = parser.parse_args()
root = args.root.resolve()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        relative = self.path.split('?', 1)[0].lstrip('/')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        start, end = 0, len(data) - 1
        request_range = self.headers.get('Range')
        if request_range:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', request_range)
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            if match[2]:
                end = min(end, int(match[2]))
            if start > end:
                self.send_error(416)
                return
        self.send_response(206 if request_range else 200)
        content_type = {
            '.m3u8': 'application/vnd.apple.mpegurl',
            '.ts': 'video/mp2t',
            '.m4s': 'video/iso.segment',
            '.mp4': 'video/mp4',
            '.flv': 'video/x-flv',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.bin': 'application/octet-stream',
        }.get(path.suffix, 'application/octet-stream')
        self.send_header('Content-Type', content_type)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if request_range:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
        self.end_headers()
        try:
            self.wfile.write(data[start:end + 1])
        except (BrokenPipeError, ConnectionResetError):
            pass


http = ThreadingHTTPServer(('127.0.0.1', 18765), Handler)
https = ThreadingHTTPServer(('127.0.0.1', 18766), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(args.cert, args.key)
https.socket = context.wrap_socket(https.socket, server_side=True)
threading.Thread(target=http.serve_forever, daemon=True).start()
print('HTTP 18765, HTTPS 18766', flush=True)
https.serve_forever()
