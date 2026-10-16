#!/usr/bin/env python3
"""Build isolated Android candidate libraries; never installs into an application."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.playback'
SOURCES = {
    'ffmpeg': ('https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/a7ebeb2bec722c1d6686d2742980c075a72c1db8', 'ac7215a1fb7862cc62a66de9331260e222f6d1fbc654936a2b1b6c024ae86f9b'),
    'wolfssl': ('https://codeload.github.com/wolfSSL/wolfssl/tar.gz/decea12e223869c8f8f3ab5a53dc90b69f436eb2', '7a5ca6f13a58a93fb2eb361ff3f556867ee9da1c0f395098c4b7b0af292366d4'),
    'dav1d': ('https://codeload.github.com/videolan/dav1d/tar.gz/42b2b24fb8819f1ed3643aa9cf2a62f03868e3aa', 'e26d41e2f496c1598f418726b871ce252ce9f18f8dbe3ad199349a42ed2cb02f'),
    'pkgconf': ('https://distfiles.ariadne.space/pkgconf/pkgconf-2.3.0.tar.xz', '3a9080ac51d03615e7c1910a0a2a8df08424892b5f13b0628a204d3fcce0ea8b'),
}
NDK_VERSION = '28.2.13676358'
AVBUILD_REVISION = '825de1a509a6321c8f7c3700688badecf77c9e69'
# Android playback patches from the pinned upstream avbuild revision. Do not
# import desktop, encoder or subtitle patches from the generic build pipeline.
PLAYBACK_PATCHES = ['0001-wolfssl-verify-hostname.patch']
PATCHES = ['0005-', '0006-', '0008-', '0013-', '0017-', '0023-', '0024-', '0027-', '0033-']


def run(args, cwd=ROOT, env=None):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def source(name):
    url, expected = SOURCES[name]
    cache = WORK / 'sources'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (name + ('.tar.xz' if name == 'pkgconf' else '.tar.gz'))
    if not archive.exists():
        temporary = archive.with_suffix('.part')
        urllib.request.urlretrieve(url, temporary)
        temporary.rename(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Archive checksum mismatch: {archive}')
    destination = WORK / 'pristine' / name
    if not destination.exists():
        destination.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                relative = Path(*Path(member.name).parts[1:])
                if relative.is_absolute() or '..' in relative.parts or member.issym() or member.islnk():
                    raise RuntimeError(f'Unsupported archive entry: {member.name}')
                if str(relative) == '.':
                    continue
                member.name = str(relative)
                tar.extract(member, destination)
    return destination


def apply_playback_patches(ff):
    # Probe the patch itself rather than the old .patched marker: existing
    # work directories predate these local security fixes.
    for name in PLAYBACK_PATCHES:
        patch = ROOT / 'playback' / name
        # Check reverse first: an insertion-only patch may still apply forward
        # after it is present, silently duplicating the security check.
        reverse = ['patch', '-p1', '--batch', '--force', '--fuzz=0', '--reverse', '--dry-run', '-i', patch]
        applied = subprocess.run(list(map(str, reverse)), cwd=ff,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if applied.returncode == 0:
            continue
        forward = ['patch', '-p1', '--batch', '--force', '--fuzz=0', '--forward', '-i', patch]
        run([*forward, '--dry-run'], ff)
        run(forward, ff)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ndk', required=True, type=Path)
    parser.add_argument('--cmake-bin', required=True, type=Path)
    parser.add_argument('--meson', required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--incremental-only', action='store_true',
                        help='Reuse matching configured builds and installed dependencies')
    args = parser.parse_args()
    args.ndk = args.ndk.resolve()
    if f'Pkg.Revision = {NDK_VERSION}' not in (args.ndk / 'source.properties').read_text():
        raise RuntimeError(f'Expected NDK {NDK_VERSION}')
    host = 'darwin-x86_64' if os.uname().sysname == 'Darwin' else 'linux-x86_64'
    llvm = args.ndk / 'toolchains/llvm/prebuilt' / host / 'bin'
    env = os.environ.copy()
    env['PATH'] = f'{args.cmake_bin.resolve()}:{llvm}:{env["PATH"]}'
    env.pop('PKG_CONFIG_PATH', None)
    env.pop('PKG_CONFIG_LIBDIR', None)
    cmake = args.cmake_bin.resolve() / 'cmake'
    if not subprocess.check_output([str(cmake), '--version'], text=True).splitlines()[0].startswith('cmake version 3.31.5'):
        raise RuntimeError('Expected CMake 3.31.5')
    if subprocess.check_output([str(args.meson.resolve()), '--version'], text=True).strip() != '1.7.2':
        raise RuntimeError('Expected Meson 1.7.2')
    src = {name: source(name) for name in SOURCES}
    host_prefix = WORK / 'host'
    pkg_build = WORK / 'pkgconf-build'
    pkg_build.mkdir(exist_ok=True)
    if not (host_prefix / 'bin/pkgconf').exists():
        run([src['pkgconf'] / 'configure', f'--prefix={host_prefix}', '--disable-shared'], pkg_build)
        run(['make', f'-j{args.jobs}', 'install'], pkg_build)
    pkg_config = host_prefix / 'bin/pkg-config'
    if not pkg_config.exists():
        pkg_config.symlink_to('pkgconf')
    env['PATH'] = f'{host_prefix / "bin"}:{env["PATH"]}'
    ff = WORK / 'ffmpeg-source'
    if not ff.exists():
        shutil.copytree(src['ffmpeg'], ff)
        for prefix in PATCHES:
            patch, = (ROOT / 'patches/master').glob(prefix + '*.patch')
            # Fail closed if the checked-in patch differs from the pinned source.
            original = subprocess.check_output(['git', 'show', f'{AVBUILD_REVISION}:{patch.relative_to(ROOT)}'], cwd=ROOT)
            if patch.read_bytes() != original:
                raise RuntimeError(f'Unreviewed patch change: {patch}')
            run(['patch', '-p1', '--batch', '-i', patch], ff)
        (ff / '.patched').write_text(AVBUILD_REVISION)
    if not (ff / '.patched').exists():
        raise RuntimeError(f'Incomplete patching; inspect and remove {ff} before retrying')
    apply_playback_patches(ff)
    flags = (ROOT / 'playback/ffmpeg.flags').read_text().splitlines()
    for abi, triple, family, cpu in [
        ('arm64-v8a', 'aarch64-linux-android', 'aarch64', 'aarch64'),
        ('armeabi-v7a', 'armv7a-linux-androideabi', 'arm', 'armv7'),
    ]:
        prefix = WORK / 'deps' / abi
        prefix.mkdir(parents=True, exist_ok=True)
        if not args.incremental_only:
            wolf_build = WORK / ('wolfssl-' + abi)
            run([cmake, '-S', src['wolfssl'], '-B', wolf_build, '-G', 'Ninja',
                 f'-DCMAKE_TOOLCHAIN_FILE={args.ndk}/build/cmake/android.toolchain.cmake',
                 f'-DANDROID_ABI={abi}', '-DANDROID_PLATFORM=android-21',
                 '-DCMAKE_BUILD_TYPE=MinSizeRel', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
                 f'-DCMAKE_INSTALL_PREFIX={prefix}', '-DBUILD_SHARED_LIBS=OFF',
                 '-DWOLFSSL_EXAMPLES=no', '-DWOLFSSL_CRYPT_TESTS=no',
                 '-DWOLFSSL_OPENSSLEXTRA=yes', '-DWOLFSSL_FILESYSTEM=yes',
                 '-DWOLFSSL_ALT_CERT_CHAINS=yes', '-DWOLFSSL_SNI=yes'], env=env)
            run([cmake, '--build', wolf_build, '--parallel', args.jobs], env=env)
            run([cmake, '--install', wolf_build], env=env)
            cross = WORK / (abi + '.ini')
            cross.write_text(f"""[binaries]
c = '{llvm}/{triple}21-clang'
ar = '{llvm}/llvm-ar'
strip = '{llvm}/llvm-strip'
[host_machine]
system = 'android'
cpu_family = '{family}'
cpu = '{cpu}'
endian = 'little'
[built-in options]
c_args = ['-fPIC']
""")
            dav_build = WORK / ('dav1d-' + abi)
            if not (dav_build / 'build.ninja').exists():
                run([args.meson.resolve(), 'setup', dav_build, src['dav1d'], '--cross-file', cross,
                     '--prefix', prefix, '--libdir', 'lib', '--default-library', 'static',
                     '--buildtype', 'minsize', '-Denable_tools=false', '-Denable_tests=false'], env=env)
            run([args.meson.resolve(), 'compile', '-C', dav_build, '-j', args.jobs], env=env)
            run([args.meson.resolve(), 'install', '-C', dav_build], env=env)
        build = WORK / ('ffmpeg-' + abi)
        build.mkdir(exist_ok=True)
        ffenv = env.copy()
        ffenv['PKG_CONFIG_LIBDIR'] = str(prefix / 'lib/pkgconfig')
        configure = [ff / 'configure', *flags, '--extra-version=naki-playback-candidate',
                     '--target-os=android', '--enable-cross-compile', f'--arch={family}',
                     f'--cc={llvm}/{triple}21-clang', f'--cxx={llvm}/{triple}21-clang++',
                     f'--ar={llvm}/llvm-ar', f'--nm={llvm}/llvm-nm',
                     f'--ranlib={llvm}/llvm-ranlib', f'--strip={llvm}/llvm-strip',
                     f'--pkg-config={pkg_config}', '--pkg-config-flags=--static',
                     '--extra-cflags=-fPIC -ffunction-sections -fdata-sections',
                     '--extra-ldflags=-Wl,--no-undefined -Wl,--gc-sections -Wl,-z,max-page-size=16384 -Wl,--no-rosegment']
        if args.incremental_only:
            wolf_options = (prefix / 'include/wolfssl/options.h').read_text()
            if '#define HAVE_SNI' not in wolf_options:
                raise RuntimeError(f'wolfSSL TLS server name indication is disabled for {abi}')
            if '#define WOLFSSL_ALT_CERT_CHAINS' not in wolf_options:
                raise RuntimeError(f'wolfSSL alternate trusted chains are disabled for {abi}')
            if '#define NO_FILESYSTEM' in wolf_options:
                raise RuntimeError(f'wolfSSL filesystem CA loading is disabled for {abi}')
            previous = WORK / 'output' / abi / 'evidence/configure.json'
            if not (build / 'ffbuild/config.mak').exists() or not previous.exists():
                raise RuntimeError(f'Missing configured build for {abi}')
            if json.loads(previous.read_text()) != list(map(str, configure)):
                raise RuntimeError(f'Configuration changed for {abi}; use the regular build')
        else:
            run(configure, build, ffenv)
        run(['make', f'-j{args.jobs}'], build, ffenv)
        out = WORK / 'output' / abi
        run(['bash', ROOT / 'tools/mklibffmpeg.sh', build, out], build, ffenv)
        for name in ['config.h', 'config_components.h', 'ffbuild/config.mak', 'ffbuild/config.log']:
            target = out / 'evidence' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build / name, target)
        (out / 'evidence/configure.json').write_text(json.dumps(list(map(str, configure)), indent=2))
    (WORK / 'output/sources.json').write_text(json.dumps(SOURCES, indent=2))
    recipe_files = [ROOT / 'playback/build.py', ROOT / 'playback/ffmpeg.flags', ROOT / 'tools/mklibffmpeg.sh']
    recipe_files += [ROOT / 'playback' / name for name in PLAYBACK_PATCHES]
    recipe_files += [p for pattern in PATCHES for p in (ROOT / 'patches/master').glob(pattern + '*.patch')]
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in recipe_files}
    manifest.update(ndk=NDK_VERSION, android_api=21, cmake='3.31.5', meson='1.7.2', upstream_avbuild=AVBUILD_REVISION, wolfssl_filesystem=True, wolfssl_alt_cert_chains=True, wolfssl_sni=True)
    (WORK / 'output/recipe.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
