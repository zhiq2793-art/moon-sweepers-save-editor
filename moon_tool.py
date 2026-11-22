#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moon Sweepers 团队钱包修改器（交互式）
=====================================

运行后：
  1. 自动扫描存档目录，列出所有栏位（余额 / 扇区 / 游玩时长 / 最后游玩时间）
  2. 让你选择要改的栏位
  3. 让你输入目标金额
  4. 确认后自动备份整个栏位目录，再写入 session.moon + slot.json

安全保证：
  * 原档先整目录备份到 slot-N.backup-时间戳
  * 写入前校验原档 SHA-256，写入后重新解析验证
  * 只改钱包那 16 字节里的 mantissa，scale / flags / 长度全部保持原样

技术格式（实测确认）：
  session.moon = "1PCM" + uint32 解压长度 + uint8 64 + ASCII SHA-256 + gzip(payload)
  payload 中键 "team"（前缀 \\x04）之后是 16 字节 .NET System.Decimal:
      lo(u32) mid(u32) hi(u32) flags(u32)，scale = (flags >> 16) & 0xFF
      dollars = (lo + mid*2^32 + hi*2^64) / 10^scale
  编辑器只把 mantissa 换成 目标金额 * 10^scale。

用法:
    python moon_tool.py                 # 用默认存档目录
    python moon_tool.py --root "D:\\某个目录"
    python moon_tool.py --dry-run       # 演练：不写任何文件
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

MAGIC = b"1PCM"
HASH_LEN = 64
TEAM_KEY = b"\x04team"

DEFAULT_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "AppData", "LocalLow", "DragDropGames", "MoonSweepers", "MoonSessions",
)


# ------------------------------------------------------------------ 容器
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
    if len(payload) != declared:
        raise ValueError("长度字段不一致")
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("SHA-256 校验失败")
    return payload


def build_container(payload):
    digest = hashlib.sha256(payload).hexdigest().encode("ascii")
    gz = gzip.compress(payload, 9, mtime=0)
    return MAGIC + struct.pack("<I", len(payload)) + bytes([HASH_LEN]) + digest + gz


# ------------------------------------------------------------------ 钱包
def find_wallets(payload):
    """返回 [(offset, mantissa, scale, flags, Decimal)]"""
    out, start = [], 0
    while True:
        i = payload.find(TEAM_KEY, start)
        if i < 0:
            return out
        start = i + 1
        off = i + len(TEAM_KEY)
        if off + 16 > len(payload):
            continue
        lo, mid, hi, flags = struct.unpack_from("<4I", payload, off)
        scale = (flags >> 16) & 0xFF
        if flags & 0xFF000000FF or scale > 28:
            continue
        mant = lo | (mid << 32) | (hi << 64)
        out.append((off, mant, scale, flags, Decimal(mant) / (Decimal(10) ** scale)))


def pick_wallet(payload, slot_dollars=None):
    ws = find_wallets(payload)
    if not ws:
        return None
    if slot_dollars is not None:
        for w in ws:
            if abs(float(w[4]) - float(slot_dollars)) < 1e-6:
                return w
    return ws[0]


def encode_decimal(value, scale, flags):
    mant = int(value * (Decimal(10) ** scale))
    if mant < 0 or mant >= (1 << 96):
        raise ValueError("金额超出范围")
    blob = (struct.pack("<3I", mant & 0xFFFFFFFF, (mant >> 32) & 0xFFFFFFFF,
                        mant >> 64) + struct.pack("<I", flags))
    return blob, mant


# ------------------------------------------------------------------ 工具
def session_path(slot_dir):
    direct = os.path.join(slot_dir, "session.moon")
    if os.path.exists(direct):
        return direct
    cands = [os.path.join(slot_dir, d, "session.moon")
             for d in os.listdir(slot_dir)
             if os.path.isdir(os.path.join(slot_dir, d))]
    cands = [c for c in cands if os.path.exists(c)]
    return cands[0] if len(cands) == 1 else None


def load_slot_json(slot_dir):
    p = os.path.join(slot_dir, "slot.json")
    if not os.path.exists(p):
        return None, None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f), p


def fmt_money(v):
    try:
        return "{:,.2f}".format(float(v))
    except Exception:
        return str(v)


def fmt_play(sec):
    if not sec:
        return "-"
    sec = int(sec)
    return "%d 小时 %d 分" % (sec // 3600, (sec % 3600) // 60) if sec >= 3600 \
        else "%d 分 %d 秒" % (sec // 60, sec % 60)


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MoonSweepers.exe"],
                             capture_output=True, text=True, timeout=10).stdout
        return "MoonSweepers.exe" in out
    except Exception:
        return False


def scan_slots(root):
    if not os.path.isdir(root):
        return []
    slots = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        # 只认 slot-1 / slot-2 这种，跳过 slot-1.backup-xxx
        if not name.lower().startswith("slot-"):
            continue
        if "." in name or not name.split("-", 1)[1].isdigit():
            continue
        sp = session_path(d)
        if not sp:
            continue
        meta, _ = load_slot_json(d)
        info = {"name": name, "dir": d, "session": sp, "meta": meta,
                "wallet": None, "error": None}
        try:
            payload = read_container(sp)
            w = pick_wallet(payload, (meta or {}).get("dollars"))
            if w:
                info["wallet"] = w[4]
                info["scale"] = w[2]
                info["offset"] = w[0]
        except Exception as e:
            info["error"] = str(e)
        slots.append(info)
    return slots


def ask(prompt, default=None):
    s = input(prompt).strip()
    if not s and default is not None:
        return default
    return s


def parse_money(s):
    s = s.replace(",", "").replace("$", "").replace("，", "").strip()
    return Decimal(s)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Moon Sweepers 团队钱包修改器")
    ap.add_argument("--root", default=None, help="存档根目录（MoonSessions）")
    ap.add_argument("--dry-run", action="store_true", help="演练，不写文件")
    a = ap.parse_args(argv)

    print("=" * 60)
    print("  Moon Sweepers 团队钱包修改器")
    print("=" * 60)

    root = a.root or DEFAULT_ROOT
    if not os.path.isdir(root):
        print("默认存档目录不存在：%s" % root)
        root = ask("请手动输入存档根目录（含 slot-1 的文件夹）: ")
        root = root.strip('"').strip("'")

    slots = scan_slots(root)
    if not slots:
        print("\n在 %s 下没找到任何存档。" % root)
        return 1

    print("\n存档根目录: %s\n" % root)
    print("找到 %d 个存档栏位：" % len(slots))
    for i, s in enumerate(slots, 1):
        meta = s["meta"] or {}
        if s["error"]:
            desc = "读取失败: %s" % s["error"]
        else:
            desc = "$%-14s %s 扇区   %s" % (
                fmt_money(s["wallet"]), meta.get("regions", "?"),
                fmt_play(meta.get("playSeconds")))
        if meta.get("dollars") is not None and s["wallet"] is not None:
            if abs(float(meta["dollars"]) - float(s["wallet"])) > 0.01:
                desc += "   [注意: slot.json=%.2f]" % meta["dollars"]
        print("  [%d] %-8s %s" % (i, s["name"], desc))

    print()
    while True:
        sel = ask("请选择要修改的栏位编号 (默认 1): ", "1")
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(slots):
                break
        except ValueError:
            pass
        print("  输入无效，请重新输入。")

    slot = slots[idx]
    if slot["error"]:
        print("该栏位无法解析：%s" % slot["error"])
        return 2

    cur = slot["wallet"]
    print("\n已选择 : %s" % slot["name"])
    print("存档   : %s" % slot["session"])
    print("当前钱包: $%s   (scale=%d, 位于 payload 0x%x)"
          % (cur, slot["scale"], slot["offset"]))

    while True:
        raw = ask("\n请输入目标金额（例如 500000，可带千分位）: ")
        if not raw:
            print("  金额不能为空。")
            continue
        try:
            target = parse_money(raw)
        except Exception:
            print("  无法识别，请只输入数字，例如 500000 或 1,234,567.89")
            continue
        if target < 0:
            print("  金额不能为负数。")
            continue
        break

    delta = target - cur
    print("\n将要修改：$%s  →  $%s   (%s%s)"
          % (fmt_money(cur), fmt_money(target),
             "+" if delta >= 0 else "-", fmt_money(abs(delta))))

    if game_running():
        print("\n[!] 检测到 MoonSweepers.exe 正在运行。")
        print("    请先完全退出游戏（含 Steam 云同步），否则改动会被内存状态覆盖。")
        if ask("    仍然继续吗？[y/N]: ", "n").lower() not in ("y", "yes"):
            return 3

    if ask("确认写入？[y/N]: ", "n").lower() not in ("y", "yes"):
        print("已取消，未修改任何文件。")
        return 0

    if a.dry_run:
        print("\n[dry-run] 演练模式，未写入任何文件。")
        return 0

    # ---- 备份 ----
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(root, "%s.backup-%s" % (slot["name"], stamp))
    shutil.copytree(slot["dir"], backup)
    print("\n[1/3] 已备份到 %s" % backup)

    # ---- 写入 session.moon ----
    payload = read_container(slot["session"])
    off, mant, scale, flags, _ = pick_wallet(payload, (slot["meta"] or {}).get("dollars"))
    blob, new_mant = encode_decimal(target, scale, flags)
    payload = payload[:off] + blob + payload[off + 16:]
    data = build_container(payload)

    session_files = [slot["session"]]
    bak = slot["session"] + ".bak"
    if os.path.exists(bak):
        session_files.append(bak)
    for p in session_files:
        open(p, "wb").write(data)

    # ---- 写入 slot.json ----
    meta, slot_json = load_slot_json(slot["dir"])
    if meta is not None:
        meta["dollars"] = float(target)
        order = ["lastPlayedTicks", "dollars", "regions", "playSeconds"]
        ordered = {k: meta[k] for k in order if k in meta}
        ordered.update({k: v for k, v in meta.items() if k not in ordered})
        text = json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
        open(slot_json, "w", encoding="utf-8").write(text)
        b2 = slot_json + ".bak"
        if os.path.exists(b2):
            open(b2, "w", encoding="utf-8").write(text)
    print("[2/3] 已写入 session.moon%s 与 slot.json"
          % (" 和 session.moon.bak" if len(session_files) > 1 else ""))

    # ---- 复核 ----
    check = read_container(slot["session"])
    w = pick_wallet(check)
    ok = w and abs(float(w[4]) - float(target)) < Decimal("0.000001")
    print("[3/3] 复核：现在钱包 = $%s   %s"
          % (fmt_money(w[4]) if w else "?", "OK" if ok else "失败！"))

    print("\n完成。请进游戏确认余额，并正常保存一次。")
    print("还原方法：删掉现在的 \"%s\"，把 \"%s\" 改名回 \"%s\"。"
          % (slot["name"], os.path.basename(backup), slot["name"]))
    return 0 if ok else 4


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
