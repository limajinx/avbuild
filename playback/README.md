# Android playback-only FFmpeg candidate

Status: both ARM libraries built and smoke-tested locally on 2026-09-08. Not
integrated into naki_tiktok. This is not a subtitle-free MDK SDK or a release approval.
The existing MDK core still requires authorized source access for full subtitle
implementation removal. Public FFmpeg subtitle API entry points and embedded
caption metadata handling are not removed by this profile.

## Build

Run from the repository root. Requires a host C compiler, make, patch, Python 3,
Android NDK **28.2.13676358**, Android CMake **3.31.5** (including Ninja), and Meson
**1.7.2**. Android API **21** matches both existing ABI binaries. NDK differs from
the original binary's 29.0.14206865 and is explicitly pinned and runtime-tested.

```sh
python3 -m venv .playback/venv
.playback/venv/bin/pip install meson==1.7.2
python3 playback/build.py \
  --ndk /Volumes/data/Library/Android/sdk/ndk/28.2.13676358 \
  --cmake-bin /Volumes/data/Library/Android/sdk/cmake/3.31.5/bin \
  --meson .playback/venv/bin/meson
python3 playback/audit.py \
  --readelf /Volumes/data/Library/Android/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf
```

`build.py` pins and hashes FFmpeg, wolfSSL, dav1d and host pkgconf source archives.
It uses FFmpeg commit `a7ebeb2bec722c1d6686d2742980c075a72c1db8`, matching the
existing binary's embedded version. It applies the Android-relevant patches from
avbuild `825de1a509a6321c8f7c3700688badecf77c9e69`, checks their contents against that
revision, and uses avbuild's combined-library linker. No nightly dependency package
is downloaded. TLS and dav1d are static dependencies inside libffmpeg.so.

Outputs: `.playback/output/{arm64-v8a,armeabi-v7a}/lib/libffmpeg.so`, configure/ELF
evidence and source/recipe manifests. Temporary sources, keys, logs, probes and
build products stay ignored. To reproduce from scratch, use a fresh checkout of
the same recipe commit. Byte-for-byte reproducibility across hosts was not tested.
The manually triggered `Android playback candidate` workflow is provided but has
not been run on GitHub; it does not publish a release or change an MDK SDK.

## Profile decisions

`ffmpeg.flags` starts with disabled encoders, muxers, decoders, demuxers, parsers,
filters and protocols. Exact enabled component sets are asserted by `audit.py`.

- **Required:** H.264/HEVC/VP8/VP9, AAC/Opus/Vorbis, JNI, MediaCodec, and libdav1d
  for real software AV1. The native `av1` decoder alone is not sufficient.
- **Required:** MOV (MP4/M4V/MOV), HLS, MPEG-TS, FLV and Matroska (MKV/WebM).
  FFmpeg's HLS configure dependencies also enable AAC, AC3/EAC3 demuxers and the
  AC3 parser. AC3/EAC3 decoders remain disabled; auxiliary demuxing is not an
  extension of the promised audio codec contract.
- **Required:** file, HTTP, HTTPS, HTTP proxy CONNECT (`httpproxy`), TCP, TLS, crypto and zlib. Encrypted HLS is
  configured but not yet runtime-tested; redirects and non-HTTP live protocols
  need media-contract and runtime validation.
- **Candidate playback filters:** scale/format/aformat/aresample for conversion;
  null/anull and implicit buffer sources/sinks for graph connections;
  atempo/volume for playback speed and volume. This retains conversion libraries.
  MDK's complete internal filter requirements cannot be proven from its public
  SDK and require the remaining playback matrix. No editing/subtitle/hardware
  backend filters are registered in the candidate.
- **Removed registrations:** all encoders, muxers and subtitle decoders, subtitle
  demuxers, subtitle parsers and subtitle filters. There are no wildcard enables.
  There is no libass dependency in this FFmpeg library.
- **Optional input formats, excluded only in the candidate:** AC3/EAC3, ALAC, AMR,
  APE, CFHD, Cook, DTS, DNxHD, EXR, FLAC, GIF, MJPEG, MLP/TrueHD, MSS, Nellymoser,
  PCM, ProRes, QTRLE, PNG, TIFF, rawvideo, RealVideo, VC1, WMV, and other codecs
  outside the requested whitelist. Their absence from actual server inputs is
  not established. Do not install this candidate until the input contract and
  playback matrix justify these removals. The same applies to removed FTP/RTMP/
  RTSP/UDP/data/pipe/concat and other non-whitelisted protocols.

The combined-library linker needed three focused fixes: retain avformat's
`mpegaudiotabs.o`, `lcevctab.o` and `to_upper4.o` when no avcodec duplicate exists.
The original unconditional exclusion breaks minimal builds. The candidate also
uses `--no-undefined`; symbols are checked again before device execution.

## Verified results

Existing libffmpeg baseline comes from naki_tiktok's previously built vnd release;
it was not rebuilt with the new toolchain. After includes software AV1 via dav1d.

| ABI | Before bytes (MiB) | Candidate bytes (MiB) | Reduction bytes (MiB) | Reduction |
|---|---:|---:|---:|---:|
| arm64-v8a | 8,274,888 (7.892) | 6,008,712 (5.730) | 2,266,176 (2.161) | 27.39% |
| armeabi-v7a | 6,185,492 (5.899) | 5,485,256 (5.231) | 700,236 (0.668) | 11.32% |

Candidate SHA-256:

- arm64-v8a: `1ac7d0325e9a843de11eabd5f6cfda6cab81a09793d5df6a96e55e4f992c5715`
- armeabi-v7a: `46634b5c882150013cd820d0b4d1fe67cc87ce01a7d63cfa9b7c4247c11fbb23`

Both retain **all** dynamic exports found in the original libffmpeg.so, including
the generic APIs whose implementations MDK may resolve dynamically. Both have
SONAME `libffmpeg.so`. DT_NEEDED contains only libm, libz, libandroid, libmediandk,
libdl and libc. No unresolved FFmpeg/dav1d/wolfSSL symbols were found. Full dynamic
loading compatibility still needs the remaining media cases.

Device: Mi 10, USB serial `60ef21d4`, supports both tested ABIs.

- Native probe: 14 decoder registrations, zero encoders, subtitle codecs or muxers.
- Existing MDK ELF load without libass in the isolated probe directory: passed.
- Local MP4 H.264 + AAC: both ABIs decoded video/audio and sought successfully
  over three independent open/seek/dispose cycles.
- Controlled HTTP MP4 and HTTPS MP4: same checks passed for both ABIs, with byte
  range support. HTTPS enabled certificate verification with the fixture CA.
- Headless MDK, video decoder explicitly `FFmpeg`: both ABIs completed three
  create/prepare/play/stop/dispose cycles, including prepare at 1000 ms, with
  valid video frame callbacks. Audio and subtitle tracks disabled in this probe.
- External HTTPS sample URL returned HTTP 403 from the device; not counted as
  a playback pass. Controlled HTTPS succeeded independently.
- Python and shell syntax, YAML parsing and git diff whitespace checks passed.

Fixture: https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4
Native probes are `probe.c` and `mdk_probe.cpp`. `serve_fixture.py` serves only
the specified fixture on loopback ports 18765/18766 for temporary adb reverse.
The test server and reverse mappings were stopped after validation.

## Outstanding release gates

- No Flutter/FVP build, APK replacement, rendered video, audible audio,
  pause/resume, MediaCodec runtime, HLS/encrypted HLS, FLV, MKV, WebM, HEVC or AV1
  playback matrix was performed. AV1 registration is not a decoded AV1 test.
- libmdk/libfvp/libass/libc++ and the APK are unchanged. No new total native/APK
  size or whole-stack reduction is claimed. FVP still depends on libass.
- To finish the original strict requirement, obtain MDK core source or a
  reproducible no-subtitle SDK, remove the FVP transitive libass link, rebuild both
  ABIs, pin the final MDK artifact URL/SHA-256 and run the full playback matrix.
- Bitstream-filter narrowing remains a possible follow-up; general API symbols
  cannot be pruned safely based on component registrations alone.

## TLS validation update (2026-10-16)

The playback recipe now applies the tracked
`0001-wolfssl-verify-hostname.patch` after the pinned upstream patches. For verified
client TLS connections, it configures `wolfSSL_check_domain_name` before the
handshake and fails if configuring hostname verification fails. Certificate
verification remains enabled by the caller. The patch is checked independently
of the historical `.patched` marker so existing work directories receive it;
reverse checks precede forward application to avoid duplicate insertion.

wolfSSL is explicitly built with filesystem CA loading, SNI and alternate trusted
certificate chains. Alternate chains let a peer chain terminate at a locally
trusted CA when the server also sends a cross-signed version with an unavailable
issuer. This does not add the unverified cross-certificate to the trust store;
the leaf must still validate to a trusted CA and match the requested hostname.
These options are required by the SDK packaging manifest. No codec, demuxer,
filter or protocol flags changed for this fix.

For an already configured build with the same configuration and these wolfSSL
features installed, add `--incremental-only` to the build command. It checks the
saved configure arguments and required wolfSSL options, then runs make and the
combined-library linker without rebuilding dependencies or reconfiguring FFmpeg.
Use the regular command when dependency features or configure arguments change.

On the Mi 10, isolated native probes for both ARM ABIs validated the public
`video.88shorts.com` MP4 through the existing system HTTP proxy, using both the
exported Android root bundle and its standalone GTS Root R4. Each case decoded
H.264/AAC, sought, and completed three open/seek/dispose cycles. Controlled local
HTTPS fixtures also accepted a matching hostname with the trusted CA and rejected
an unknown CA, a wrong SAN (even with a matching common name), and an expired
leaf. These are native transport/decode checks; Flutter rendering and audible
playback remain separate application checks. Fixture private keys, device test
directories and the temporary adb reverse mapping were removed after testing.
