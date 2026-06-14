"""端到端串口测试 — 通过 COM2/COM3 虚拟串口对测试核心模块.

使用方法:
    python tools/test_serial.py

前提: COM2 和 COM3 已通过 ELTIMA VSPD 配对桥接。
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path

import serial

# 将项目根目录加入 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.protocol import Protocol, Frame
from core.protocol_config import ProtocolConfig

# ── 配置 ───────────────────────────────────────────────────────────

COM_DEVICE = "COM3"  # 虚拟下位机
COM_APP = "COM2"     # 虚拟上位机
BAUDRATE = 115200
TIMEOUT = 3.0


# ── 虚拟设备响应逻辑（复用 virtual_pair.py）──────────────────────────

def handle_cmd(cmd: int, data: bytes) -> bytes | None:
    """模拟下位机对各命令的响应."""
    if cmd == 0x01:
        return bytes([0x01, 0x02, 0x03, 0x00])
    elif cmd == 0x02:
        return bytes([0x00, 0x01, 0x03, 0x12, 0x34, 0x56, 0x78])
    elif cmd == 0x03:
        temp = random.randint(200, 350)
        humi = random.randint(400, 800)
        return temp.to_bytes(2, "big") + humi.to_bytes(2, "big") + bytes([0x01, 0, 0, 0])
    elif cmd == 0x04:
        item = data[0] if data else 0
        db = {0x01: b'\x00\x0A', 0x02: b'\x01\x2C', 0x03: b'\x00\x01', 0x04: b'\x00\x64'}
        return db.get(item, b'\xFF\xFF')
    elif cmd == 0x05:
        return bytes([0x01])
    elif cmd == 0x10:
        if len(data) >= 5:
            steps = int.from_bytes(data[3:5], "big")
            return bytes([0x01]) + min(steps, 1000).to_bytes(2, "big")
        return bytes([0x00, 0x00, 0x00])
    elif cmd == 0x11:
        return bytes([0x01]) if len(data) >= 2 and data[0] <= 15 else bytes([0x00])
    elif cmd == 0x20:
        if len(data) >= 3:
            addr = int.from_bytes(data[0:2], "big")
            ln = data[2]
            return bytes([(addr + i) & 0xFF for i in range(min(ln, 8))]).ljust(8, b"\x00")
        return bytes(8)
    elif cmd == 0xF0:
        return bytes([0x01])
    elif cmd == 0xFF:
        return b""
    return bytes([0x00])


# ── 虚拟设备线程 ───────────────────────────────────────────────────

class DeviceThread(threading.Thread):
    """COM3 端虚拟下位机，接收帧并响应."""

    def __init__(self, proto: Protocol, port: str = COM_DEVICE):
        super().__init__(daemon=True)
        self._proto = proto
        self._port = port
        self._running = False
        self._serial: serial.Serial | None = None
        self.handled_count = 0

    def run(self):
        self._serial = serial.Serial(self._port, BAUDRATE, timeout=0.1)
        self._running = True
        buf = b""
        while self._running:
            try:
                chunk = self._serial.read(256)
                if chunk:
                    buf += chunk
                    frames, buf = self._proto.decode(buf)
                    for frame in frames:
                        resp_data = handle_cmd(frame.cmd, frame.data)
                        if resp_data is not None:
                            resp_frame = self._proto.encode(frame.cmd, resp_data)
                            self._serial.write(resp_frame)
                            self.handled_count += 1
            except Exception:
                if self._running:
                    break
        if self._serial and self._serial.is_open:
            self._serial.close()

    def stop(self):
        self._running = False


# ── 测试框架 ───────────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.details: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = ""):
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        self.details.append((name, ok, detail))

    def summary(self) -> str:
        lines = []
        for name, ok, detail in self.details:
            tag = "PASS" if ok else "FAIL"
            line = f"  [{tag}] {name}"
            if detail:
                line += f"  -- {detail}"
            lines.append(line)
        total = self.passed + self.failed
        lines.append(f"\n  Result: {self.passed}/{total} PASS, {self.failed} FAIL")
        return "\n".join(lines)


def send_and_recv(ser: serial.Serial, proto: Protocol, cmd: int, data: bytes) -> Frame | None:
    """通过串口发送一帧并等待响应."""
    frame = proto.encode(cmd, data)
    ser.write(frame)
    ser.flush()

    buf = b""
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            frames, buf = proto.decode(buf)
            if frames:
                return frames[0]
        else:
            time.sleep(0.01)
    return None


# ── 测试用例 ───────────────────────────────────────────────────────

def test_all_commands(proto: Protocol, ser: serial.Serial, result: TestResult):
    """测试所有查询命令的收发."""
    commands = [
        (0x01, b"",           "查询版本",    4),
        (0x02, b"",           "查询设备信息", 7),
        (0x03, bytes([0x01]), "查询温湿度",   8),
        (0x04, bytes([0x01]), "读取配置",     2),
        (0x05, bytes([0x01, 0x00, 0x0A]), "写入配置", 1),
        (0x10, bytes([0x01, 0x00, 0x64, 0x00, 0x0A]), "控制电机", 3),
        (0x11, bytes([0x03, 0x01]), "GPIO控制", 1),
        (0x20, bytes([0x00, 0x10, 0x08]), "批量读取", 8),
        (0xF0, b"",           "设备复位",     1),
        (0xFF, b"",           "心跳",         0),
    ]

    for cmd, data, name, expected_len in commands:
        resp = send_and_recv(ser, proto, cmd, data)
        if resp is None:
            result.add(f"命令[{name}] 0x{cmd:02X}", False, "超时无响应")
            continue

        ok_cmd = resp.cmd == cmd
        ok_len = len(resp.data) == expected_len
        ok = ok_cmd and ok_len
        detail = f"CMD=0x{resp.cmd:02X} DATA_LEN={len(resp.data)}"
        if not ok_cmd:
            detail += f" (期望CMD=0x{cmd:02X})"
        if not ok_len:
            detail += f" (期望LEN={expected_len})"
        result.add(f"命令[{name}] 0x{cmd:02X}", ok, detail)


def test_frame_format(proto: Protocol, ser: serial.Serial, result: TestResult):
    """验证帧格式: 帧头、帧尾、CRC 正确."""
    resp = send_and_recv(ser, proto, 0x01, b"")
    if resp is None:
        result.add("帧格式", False, "超时")
        return

    raw = resp.raw
    cfg = proto.config
    ok_header = raw[:len(cfg.header)] == cfg.header
    ok_tail = raw[-len(cfg.tail):] == cfg.tail
    # 用 Protocol 内部的校验算法验证
    payload = resp.cmd.to_bytes(cfg.cmd_size, cfg.byte_order) + resp.data
    expected_crc = proto._calc_crc(payload)
    actual_crc = raw[-len(cfg.tail) - cfg.crc_size: -len(cfg.tail)]
    ok_crc = actual_crc == expected_crc

    ok = ok_header and ok_tail and ok_crc
    detail = f"header={'OK' if ok_header else 'BAD'} tail={'OK' if ok_tail else 'BAD'} crc={'OK' if ok_crc else 'BAD'}"
    result.add("帧格式校验", ok, detail)


def test_multi_frame_in_one_send(proto: Protocol, ser: serial.Serial, result: TestResult):
    """粘包测试: 一次发送多帧，验证全部正确响应."""
    frames_data = [
        (0x01, b""),
        (0x04, bytes([0x01])),
        (0xFF, b""),
    ]
    # 一次性写入所有帧
    combined = b""
    for cmd, data in frames_data:
        combined += proto.encode(cmd, data)
    ser.write(combined)
    ser.flush()

    # 读取所有响应
    buf = b""
    received = []
    deadline = time.time() + TIMEOUT
    while time.time() < deadline and len(received) < len(frames_data):
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            frames, buf = proto.decode(buf)
            received.extend(frames)
        else:
            time.sleep(0.01)

    ok_count = len(received) == len(frames_data)
    ok_cmds = all(received[i].cmd == frames_data[i][0] for i in range(min(len(received), len(frames_data))))
    ok = ok_count and ok_cmds

    detail = f"发送{len(frames_data)}帧 收到{len(received)}帧"
    if received:
        detail += f" CMDs={[hex(f.cmd) for f in received]}"
    result.add("粘包测试", ok, detail)


def test_partial_frame(proto: Protocol, ser: serial.Serial, result: TestResult):
    """半包测试: 分段发送一帧，验证设备端能正确拼接响应."""
    frame = proto.encode(0x01, b"")
    # 分成两段发送
    mid = len(frame) // 2
    ser.write(frame[:mid])
    ser.flush()
    time.sleep(0.05)
    ser.write(frame[mid:])
    ser.flush()

    buf = b""
    deadline = time.time() + TIMEOUT
    resp = None
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            frames, buf = proto.decode(buf)
            if frames:
                resp = frames[0]
                break
        else:
            time.sleep(0.01)

    ok = resp is not None and resp.cmd == 0x01
    detail = f"CMD=0x{resp.cmd:02X}" if resp else "无响应"
    result.add("半包测试", ok, detail)


def test_crc_error_rejected(proto: Protocol, ser: serial.Serial, result: TestResult):
    """CRC 错误帧应被设备端丢弃，不响应.

    先发 CRC 错误帧，等待处理后再发正常帧，
    验证正常帧仍能被正确处理（说明错误帧被跳过了）。
    """
    # 构造 CRC 错误帧
    bad_frame = proto.encode(0x01, b"")
    bad_crc = bytearray(bad_frame)
    bad_crc[-3] ^= 0xFF  # 篡改 CRC
    bad_frame = bytes(bad_crc)

    # 先发错误帧，等设备处理完
    ser.write(bad_frame)
    ser.flush()
    time.sleep(0.2)

    # 再发正常帧
    resp = send_and_recv(ser, proto, 0xFF, b"")

    ok = resp is not None and resp.cmd == 0xFF
    detail = f"收到CMD=0x{resp.cmd:02X}" if resp else "无响应"
    result.add("CRC错误帧丢弃", ok, detail)


def test_raw_bytes_echo(proto: Protocol, ser: serial.Serial, result: TestResult):
    """原始字节测试: 发送非协议数据，验证不影响后续帧解析."""
    # 先发一段垃圾数据（避免包含 AA 字节，防止误匹配帧头）
    garbage = b"\x00\x11\x22\x33\x44"
    ser.write(garbage)
    ser.flush()
    time.sleep(0.2)  # 等设备处理完垃圾数据

    # 再发正常帧
    resp = send_and_recv(ser, proto, 0x01, b"")
    ok = resp is not None and resp.cmd == 0x01
    detail = f"CMD=0x{resp.cmd:02X}" if resp else "无响应"
    result.add("垃圾数据后恢复", ok, detail)


def test_rapid_fire(proto: Protocol, ser: serial.Serial, result: TestResult):
    """快速连续发送: 不等待响应，连续发 10 帧心跳."""
    count = 10
    for _ in range(count):
        frame = proto.encode(0xFF, b"")
        ser.write(frame)
    ser.flush()

    buf = b""
    received = []
    deadline = time.time() + TIMEOUT
    while time.time() < deadline and len(received) < count:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            frames, buf = proto.decode(buf)
            received.extend(frames)
        else:
            time.sleep(0.01)

    ok = len(received) == count
    ok_cmds = all(f.cmd == 0xFF for f in received)
    ok = ok and ok_cmds
    detail = f"发送{count}帧 收到{len(received)}帧"
    result.add("快速连续发送", ok, detail)


def test_crc_types(result: TestResult):
    """测试不同 CRC 类型的编解码（纯本地，不走串口）."""
    for crc_type, crc_size in [("CRC16-MODBUS", 2), ("CRC16-CCITT", 2), ("CRC32", 4), ("NONE", 0)]:
        cfg = ProtocolConfig(crc_type=crc_type, crc_size=crc_size)
        p = Protocol(cfg)
        frame = p.encode(0x01, b"\x01\x02")
        frames, remaining = p.decode(frame)
        ok = len(frames) == 1 and frames[0].cmd == 0x01 and frames[0].data == b"\x01\x02"
        result.add(f"CRC类型[{crc_type}]", ok, f"帧长={len(frame)}")


def test_protocol_config_roundtrip(result: TestResult):
    """测试 ProtocolConfig 的序列化/反序列化."""
    cfg = ProtocolConfig()
    d = cfg.to_dict()
    cfg2 = ProtocolConfig.from_dict(d)
    ok = cfg == cfg2
    result.add("ProtocolConfig 序列化往返", ok)


def test_large_data(proto: Protocol, ser: serial.Serial, result: TestResult):
    """测试较大数据帧的收发."""
    # CMD 0x20 批量读取，构造较长的响应数据
    data = bytes([0x00, 0x00, 0x08])  # 起始地址=0, 长度=8
    resp = send_and_recv(ser, proto, 0x20, data)
    ok = resp is not None and resp.cmd == 0x20 and len(resp.data) == 8
    detail = f"CMD=0x{resp.cmd:02X} DATA_LEN={len(resp.data) if resp else 0}"
    result.add("大数据帧", ok, detail)


# ── 主函数 ─────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  JkeyToys 端到端串口测试")
    print(f"  设备端: {COM_DEVICE}  上位机端: {COM_APP}")
    print("=" * 55)
    print()

    # 加载协议配置
    config_dir = ROOT / "protocol"
    config_path = config_dir / "protocol.json"
    if not config_path.exists():
        config_path = config_dir / "protocol_default.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    proto_config = ProtocolConfig.from_dict(cfg["protocol"])
    proto = Protocol(proto_config)

    result = TestResult()

    # ── 本地测试（不需要串口）──
    print("[Phase 1] 本地模块测试")
    test_crc_types(result)
    test_protocol_config_roundtrip(result)
    print()

    # ── 串口测试 ──
    print("[Phase 2] 串口通信测试")

    # 启动虚拟设备
    device = DeviceThread(proto, COM_DEVICE)
    device.start()
    time.sleep(0.5)  # 等设备就绪

    try:
        ser = serial.Serial(COM_APP, BAUDRATE, timeout=0.1)
    except Exception as e:
        print(f"  无法打开 {COM_APP}: {e}")
        device.stop()
        return

    try:
        test_frame_format(proto, ser, result)
        test_all_commands(proto, ser, result)
        test_multi_frame_in_one_send(proto, ser, result)
        test_partial_frame(proto, ser, result)
        test_crc_error_rejected(proto, ser, result)
        test_raw_bytes_echo(proto, ser, result)
        test_rapid_fire(proto, ser, result)
        test_large_data(proto, ser, result)
    finally:
        ser.close()
        device.stop()

    print()
    print("=" * 55)
    print(result.summary())
    print("=" * 55)
    print(f"  设备端处理帧数: {device.handled_count}")

    return result.failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
