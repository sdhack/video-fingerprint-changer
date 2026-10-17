# -*- coding: utf-8 -*-
"""视频指纹修改核心模块。

原理:解析 MP4/MOV 文件的顶层 box,找到 free/skip 空闲原子,
把随机字符串写入其中 —— 文件大小不变,音视频数据(mdat)不动,
但整文件 MD5/SHA1 完全改变,平台去重指纹随之改变。
"""
import os
import struct
import string
import random
import zlib

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.m4a', '.mov', '.qt'}
RANDOM_CHARS = string.ascii_letters + string.digits

def random_string(n: int) -> str:
    return ''.join(random.SystemRandom().choice(RANDOM_CHARS) for _ in range(n))


def _iter_top_boxes(data: bytes):
    """解析顶层 box,产出 (type, offset, total_size, payload_size)。损坏即停止。"""
    off = 0
    n = len(data)
    while off + 8 <= n:
        size, btype = struct.unpack('>I4s', data[off:off + 8])
        header = 8
        if size == 1:  # 64位 largesize
            if off + 16 > n:
                break
            size = struct.unpack('>Q', data[off + 8:off + 16])[0]
            header = 16
        elif size == 0:  # 延伸到文件尾
            size = n - off
        if size < header or off + size > n:
            break
        yield btype, off, size, size - header
        off += size


def scan_free_spans(src: str):
    """流式顺序解析整个文件的顶层 box,返回 free/skip 原子的
    [(payload_offset, payload_size), ...]。对任意大小、任意 box 排列均可靠。"""
    spans = []
    size = os.path.getsize(src)
    with open(src, 'rb') as f:
        off = 0
        while off + 8 <= size:
            f.seek(off)
            hdr = f.read(16)
            if len(hdr) < 8:
                break
            bsize, btype = struct.unpack('>I4s', hdr[:8])
            header = 8
            to_eof = False
            if bsize == 1:  # 64位 largesize
                if len(hdr) < 16:
                    break
                bsize = struct.unpack('>Q', hdr[8:16])[0]
                header = 16
            elif bsize == 0:  # 延伸到文件尾
                bsize = size - off
                to_eof = True
            if bsize < header or off + bsize > size:
                break  # 结构损坏,停止以保证安全
            payload_start = off + header
            payload_len = bsize - header
            if btype in (b'free', b'skip') and payload_len > 0 and bsize <= 0xFFFFFFFF:
                spans.append((payload_start, payload_len))
            elif (to_eof and btype == b'\x00\x00\x00\x00' and payload_len > 32):
                # 尾部"延伸到文件尾"的全零填充 box(部分导出器留下的空白):验证后可用
                f.seek(payload_start)
                pad = f.read(min(payload_len, 4096))
                if not pad.strip(b'\x00'):
                    spans.append((payload_start, payload_len))
            off += bsize
    return spans


def plan_randomize(src: str) -> dict:
    """制定修改方案。返回 None 表示找不到可用空闲区。"""
    spans = scan_free_spans(src)
    if not spans:
        return None
    return {'candidates': spans, 'size': os.path.getsize(src)}


def make_fingerprint(src: str, dst: str, min_len=24, max_len=128, allow_append=False) -> str:
    """基于 src 生成指纹已修改的副本 dst。

    默认严格保持大小不变(写入 free/skip 空闲原子);
    allow_append=True 时,若找不到空闲原子则在文件尾部附加随机串(文件会略微增大)。
    随机串在拷贝过程中直接注入,同时增量计算 CRC32,只读写一遍文件。
    返回输出文件的 6 位 CRC 校验码(大写十六进制)。
    """
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError('输出路径不能与源文件相同')

    plan = plan_randomize(src)
    if plan is None and not allow_append:
        raise ValueError('未找到 free/skip 空闲原子(可勾选"尾部附加模式"重试)')

    inject_off = None
    inject = b''
    if plan is None:
        # 兜底:文件尾部附加随机串(文件会略微增大)
        inject = random_string(random.randint(min_len, max_len)).encode('ascii')
    else:
        off, payload = max(plan['candidates'], key=lambda s: s[1])
        n = min(payload, random.randint(min_len, max_len))
        inject = random_string(n).encode('ascii')
        inject_off = off  # 在空闲区负载内等长替换,大小不变

    # 一遍拷贝:边拷边注入随机串,边算 CRC
    bufsize = 64 * 1024 * 1024
    crc = 0
    pos = 0
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        while True:
            chunk = fi.read(bufsize)
            if not chunk:
                break
            if inject_off is not None and pos <= inject_off < pos + len(chunk):
                rel = inject_off - pos
                chunk = chunk[:rel] + inject + chunk[rel + len(inject):]  # 等长替换,大小不变
                inject_off = None  # 只注入一次
            crc = zlib.crc32(chunk, crc)
            fo.write(chunk)
            pos += len(chunk)

    if plan is None:
        # 兜底模式:随机串附加到文件尾
        crc = zlib.crc32(inject, crc)
        with open(dst, 'ab') as fo:
            fo.write(inject)

    return format(crc & 0xFFFFFF, '06X')


def fingerprint_inplace(src: str, min_len=24, max_len=128) -> int:
    """直接原地修改文件指纹(大小不变)。"""
    plan = plan_randomize(src)
    if plan is None:
        raise ValueError('未找到 free/skip 空闲原子')
    off, payload = max(plan['candidates'], key=lambda s: s[1])
    n = min(payload, random.randint(min_len, max_len))
    with open(src, 'r+b') as f:
        f.seek(off)
        f.write(random_string(n).encode('ascii'))
    return n


def file_hash(path: str, algo='md5') -> str:
    import hashlib
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()
