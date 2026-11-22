#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moon Sweepers 存档金币（团队钱包）修改工具 —— 已验证版
=====================================================

存档容器格式（实测确认）:

    session.moon = "1PCM"
                 + uint32 LE   解压后长度
                 + uint8       哈希串长度 (0x40 = 64)
                 + ASCII(64)   SHA-256(解压后 payload) 小写十六进制
                 + gzip 流

    payload 内部: 头部 + 地形 JSON + 世界数据 + 尾部键值记录。
    团队钱包是键 "team" 记录里的 16 字节 .NET System.Decimal:

        <80 长度前缀> 'team'
        lo   uint32
        mid  uint32
        hi   uint32
        flags uint32          scale = (flags >> 16) & 0xFF

        dollars = (lo + mid*2^32 + hi*2^64) / 10^scale
        本机实测 scale = 18，例: 9.446536949867951

用法:
    python moon_wallet.py inspect --save-dir "<含 session.moon 的目录>"
    python moon_wallet.py patch   --save-dir "<...>" --target 500000 [--dry-run]
    python moon_wallet.py hexdump <文件> [--offset N] [--length N]

原档绝不覆盖：输出为 <out-dir>/session.modified.moon 与 slot.modified.json。
"""
import argparse
import gzip
import hashlib
import json
import os
import struct
import sys
from decimal import Decimal

MAGIC = b"1PCM"
HASH_LEN = 64
TEAM_KEY = b"\x04team"


# ---------------------------------------------------------------- 容器
def read_container(path):
    raw = open(path, "rb").read()
    if raw[:4] != MAGIC:
        raise ValueError("不是 1PCM 容器: %r" % raw[:4])
    declared = struct.unpack("<I", raw[4:8])[0]
    hlen = raw[8]
    if hlen != HASH_LEN:
        raise ValueError("哈希长度异常: %d" % hlen)
    digest = raw[9:9 + hlen].decode("ascii")
    payload = gzip.decompress(raw[9 + hlen:])
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest:
        raise ValueError("SHA-256 不匹配")
    if declared != len(payload):
        raise ValueError("长度字段不匹配")
    return payload, {"raw_size": len(raw), "payload_size": len(payload),
                     "sha256": digest, "gzip_size": len(raw) - 9 - hlen}


def build_container(payload, level=9):
    digest = hashlib.sha256(payload).hexdigest().encode("ascii")
    gz = gzip.compress(payload, level, mtime=0)
    return MAGIC + struct.pack("<I", len(payload)) + bytes([HASH_LEN]) + digest + gz


def verify_container(data):
    if data[:4] != MAGIC:
        return False
    hlen = data[8]
    payload = gzip.decompress(data[9 + hlen:])
    return (hashlib.sha256(payload).hexdigest().encode() == data[9:9 + hlen]
            and struct.unpack("<I", data[4:8])[0] == len(payload))


# ---------------------------------------------------------------- 结构
def read_varint(buf, off):
    shift = val = 0
    while True:
        b = buf[off]
        off += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, off
        shift += 7


def parse_header(payload):
    info = {"version_u32": struct.unpack("<I", payload[0:4])[0]}
    slen, off = read_varint(payload, 4)
    info["session_id"] = payload[off:off + slen].decode("ascii", "replace")
    off += slen
    info["seed"] = struct.unpack("<i", payload[off:off + 4])[0]
    off += 4
    jlen, off = read_varint(payload, off)
    info["config_len"] = jlen
    info["world_offset"] = off + jlen
    return info


def session_path(save_dir):
    """session.moon 可能在 save_dir 本身，也可能在其下的 <hash>/ 子目录。"""
    direct = os.path.join(save_dir, "session.moon")
    if os.path.exists(direct):
        return direct
    import glob
    hits = glob.glob(os.path.join(save_dir, "*", "session.moon"))
    if len(hits) != 1:
        raise ValueError("在 %s 下没找到唯一的 session.moon（找到 %d 个）"
                         % (save_dir, len(hits)))
    return hits[0]


# ---------------------------------------------------------------- 钱包
def find_wallets(payload):
    """返回所有 "team" 记录后的 decimal: [(offset, mantissa, scale, value)]"""
    out = []
    start = 0
    while True:
        i = payload.find(TEAM_KEY, start)
        if i < 0:
            break
        off = i + len(TEAM_KEY)
        start = i + 1
        if off + 16 > len(payload):
            continue
        lo, mid, hi, flags = struct.unpack_from("<4I", payload, off)
        scale = (flags >> 16) & 0xFF
        if flags & 0xFF000000FF:          # 保留位/符号位必须为 0
            continue
        if scale > 28:
            continue
        mant = lo | (mid << 32) | (hi << 64)
        value = Decimal(mant) / (Decimal(10) ** scale)
        out.append((off, mant, scale, value))
    return out


def encode_decimal(value, scale, flags):
    mant = int(value * (Decimal(10) ** scale))
    if mant < 0 or mant >= (1 << 96):
        raise ValueError("数值超出 decimal 96 位范围")
    return (struct.pack("<3I", mant & 0xFFFFFFFF, (mant >> 32) & 0xFFFFFFFF,
                        mant >> 64) + struct.pack("<I", flags)), mant


# ---------------------------------------------------------------- slot.json
def load_slot(save_dir):
    here = os.path.join(save_dir, "slot.json")
    parent = os.path.join(os.path.dirname(os.path.abspath(save_dir)), "slot.json")
    p = here if os.path.exists(here) else parent
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f), p


def dump_slot(d):
    order = ["lastPlayedTicks", "dollars", "regions", "playSeconds"]
    o = {k: d[k] for k in order if k in d}
    o.update({k: v for k, v in d.items() if k not in o})
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- 命令
def cmd_inspect(a):
    save_dir = os.path.abspath(a.save_dir)
    payload, info = read_container(session_path(save_dir))
    slot, slot_path = load_slot(save_dir)

    print("=" * 68)
    print("存档目录 : %s" % save_dir)
    print("容器     : 1PCM + 长度 %d + SHA-256 + gzip(%d 字节)"
          % (info["payload_size"], info["gzip_size"]))
    print("校验     : 通过（SHA-256 与长度均一致）")
    hdr = parse_header(payload)
    print("会话 ID  : %s" % hdr["session_id"])
    print("seed     : %d    世界数据起始: 0x%x"
          % (hdr["seed"], hdr["world_offset"]))
    print("-" * 68)
    print("slot.json: %s" % slot_path)
    print("  dollars = %.17g   regions = %s   playSeconds = %r"
          % (slot["dollars"], slot.get("regions"), slot.get("playSeconds")))
    print("-" * 68)
    ws = find_wallets(payload)
    print("team 钱包记录: %d 处" % len(ws))
    for off, mant, scale, value in ws:
        print("  0x%06x  scale=%-2d  mantissa=%-22d  = $%s"
              % (off, scale, mant, value))
        print("           原始 16 字节: %s"
              % payload[off:off + 16].hex(" "))
        if abs(float(value) - float(slot["dollars"])) < 1e-6:
            print("           ← 与 slot.json 的 dollars 完全一致")


def cmd_patch(a):
    save_dir = os.path.abspath(a.save_dir)
    out_dir = os.path.abspath(a.out_dir or os.getcwd())
    os.makedirs(out_dir, exist_ok=True)

    payload, _ = read_container(session_path(save_dir))
    slot, _ = load_slot(save_dir)
    target = Decimal(str(a.target))

    ws = find_wallets(payload)
    if not ws:
        print("[!] 没找到 team 钱包记录")
        return 2
    # 取与 slot.json 金额一致的那条；否则取第一条
    best = None
    for item in ws:
        if abs(float(item[3]) - float(slot["dollars"])) < 1e-6:
            best = item
            break
    best = best or ws[0]
    off, mant, scale, value = best

    flags = struct.unpack_from("<I", payload, off + 12)[0]
    blob, new_mant = encode_decimal(target, scale, flags)
    print("钱包位置 : 0x%06x  (scale=%d)" % (off, scale))
    print("当前金额 : $%s   (slot.json: %.17g)" % (value, slot["dollars"]))
    print("目标金额 : $%s" % target)
    print("新 mantissa: %d" % new_mant)

    if a.dry_run:
        print("[dry-run] 未写入")
        return 0

    payload = payload[:off] + blob + payload[off + 16:]
    data = build_container(payload)
    if not verify_container(data):
        print("[!] 自检失败")
        return 3

    sess_out = os.path.join(out_dir, "session.modified.moon")
    open(sess_out, "wb").write(data)
    print("[ok] %s  (%d 字节, 已重算 SHA-256/gzip)" % (sess_out, len(data)))

    slot_new = dict(slot)
    slot_new["dollars"] = float(target)
    slot_out = os.path.join(out_dir, "slot.modified.json")
    open(slot_out, "w", encoding="utf-8").write(dump_slot(slot_new))
    print("[ok] %s  (%d 字节)" % (slot_out, os.path.getsize(slot_out)))

    # 复核
    p2, _ = read_container(sess_out)
    check = [w for w in find_wallets(p2) if w[0] == off][0]
    assert check[1] == new_mant, "复核失败"
    print("[ok] 复核通过：新存档里该位置 = $%s" % check[3])
    return 0


def cmd_hexdump(a):
    d = open(a.file, "rb").read()
    off, end = a.offset or 0, min(len(d), (a.offset or 0) + (a.length or 256))
    for i in range(off, end, 16):
        c = d[i:i + 16]
        print("%08x  %-47s  %s" % (i, " ".join("%02x" % b for b in c),
                                   "".join(chr(b) if 32 <= b <= 126 else "."
                                           for b in c)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Moon Sweepers 团队钱包修改器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="解析并显示钱包")
    p.add_argument("--save-dir", required=True)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("patch", help="生成修改后的存档")
    p.add_argument("--save-dir", required=True)
    p.add_argument("--target", required=True, help="目标金额，如 500000")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("hexdump", help="十六进制查看")
    p.add_argument("file")
    p.add_argument("--offset", type=lambda s: int(s, 0), default=0)
    p.add_argument("--length", type=lambda s: int(s, 0), default=256)
    p.set_defaults(func=cmd_hexdump)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
