#!/usr/bin/env python3
"""Reject unexpected configured components and capture ELF evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

EXPECTED = {
    'ENCODER': set(), 'MUXER': set(),
    'DEMUXER': set('aac ac3 eac3 flv hls matroska mov mpegts'.split()),
    'PARSER': set('aac aac_latm ac3 amr av1 h264 hevc mlp opus vorbis vp8 vp9'.split()),
    'FILTER': set('aformat anull aresample atempo volume format null scale'.split()),
    'PROTOCOL': set('crypto file http https tcp tls'.split()),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--readelf', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('.playback/output'))
    args = parser.parse_args()
    report = {}
    for abi in ['arm64-v8a', 'armeabi-v7a']:
        root = args.output / abi
        config = (root / 'evidence/config_components.h').read_text()
        enabled_decoders = {s.lower() for s in re.findall(r'^#define CONFIG_(\w+)_DECODER 1$', config, re.M)}
        baseline_decoders = set((Path(__file__).with_name('decoder-compatibility.txt')).read_text().split())
        missing_decoders = baseline_decoders - enabled_decoders
        if missing_decoders:
            raise RuntimeError(f'{abi} lost baseline non-subtitle decoders: {missing_decoders}')
        forbidden_decoders = set('ass ccaption dvbsub dvdsub jacosub libzvbi_teletext microdvd movtext mpl2 pgssub realtext sami srt ssa subrip subviewer subviewer1 text webvtt xsub'.split())
        present_forbidden = forbidden_decoders & enabled_decoders
        if present_forbidden:
            raise RuntimeError(f'{abi} subtitle decoders enabled: {present_forbidden}')
        for kind, expected in EXPECTED.items():
            enabled = {s.lower() for s in re.findall(r'^#define CONFIG_(\w+)_' + kind + r' 1$', config, re.M)}
            if enabled != expected:
                raise RuntimeError(f'{abi} {kind}: unexpected={enabled-expected}, missing={expected-enabled}')
        binary = root / 'lib/libffmpeg.so'
        elf = subprocess.check_output([str(args.readelf), '-d', str(binary)], text=True)
        if not re.search(r'\(SONAME\).*\[libffmpeg.so\]', elf):
            raise RuntimeError('Unexpected FFmpeg SONAME')
        nm = args.readelf.parent / 'llvm-nm'
        symbols = subprocess.check_output([str(nm), '-D', str(binary)], text=True)
        if re.search(r'\bU (?:ff_|av|swr_|sws_|dav1d_|wolfSSL)', symbols):
            raise RuntimeError('Unresolved media symbol')
        for required in ['avcodec_send_packet', 'avcodec_receive_frame', 'avformat_open_input', 'avfilter_graph_alloc', 'swr_alloc', 'sws_getContext', 'av_jni_set_java_vm']:
            if not re.search(r'\bT ' + required + r'(?:@@?\w+)?$', symbols, re.M):
                raise RuntimeError(f'Missing export: {required}')
        (root / 'evidence/symbols.txt').write_text(symbols)
        if 'libass' in elf or 'libdav1d.so' in elf or 'libwolfssl.so' in elf:
            raise RuntimeError('Unexpected external media library dependency')
        (root / 'evidence/dynamic.txt').write_text(elf)
        report[abi] = {'bytes': binary.stat().st_size,
                       'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                       'needed': re.findall(r'\(NEEDED\).*?\[(.*?)\]', elf)}
    (args.output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
