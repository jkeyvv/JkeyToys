"""串口收发工作线程."""

from __future__ import annotations

import serial
import serial.tools.list_ports
from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition

from core.protocol import Protocol, Frame, DEFAULT_PROTOCOL


def list_serial_ports() -> list[str]:
    """列出系统可用串口."""
    return [p.device for p in serial.tools.list_ports.comports()]


class SerialWorker(QThread):
    """串口收发工作线程.

    信号:
        data_received(bytes): 收到的原始字节数据
        frame_received(Frame): 解析出的协议帧
        error_occurred(str): 错误信息
        connection_changed(bool): 连接状态变化
    """

    data_received = Signal(bytes)
    frame_received = Signal(Frame)
    error_occurred = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, protocol: Protocol | None = None, parent=None):
        super().__init__(parent)
        self._protocol = protocol or DEFAULT_PROTOCOL
        self._serial: serial.Serial | None = None
        self._running = False
        self._buffer = b""
        self._tx_mutex = QMutex()
        self._tx_data: bytes | None = None
        self._tx_condition = QWaitCondition()

    def set_protocol(self, protocol: Protocol):
        """更新协议实例."""
        self._protocol = protocol

    def open_port(
        self,
        port: str,
        baudrate: int = 115200,
        databits: int = 8,
        stopbits: float = 1,
        parity: str = "None",
    ) -> bool:
        """打开串口.

        Args:
            port: 串口名称 (如 COM3, /dev/ttyUSB0)
            baudrate: 波特率
            databits: 数据位 (5/6/7/8)
            stopbits: 停止位 (1/1.5/2)
            parity: 校验位 (None/Even/Odd/Mark/Space)

        Returns:
            是否成功打开
        """
        parity_map = {
            "None": serial.PARITY_NONE,
            "Even": serial.PARITY_EVEN,
            "Odd": serial.PARITY_ODD,
            "Mark": serial.PARITY_MARK,
            "Space": serial.PARITY_SPACE,
        }
        stopbits_map = {
            1: serial.STOPBITS_ONE,
            1.5: serial.STOPBITS_ONE_POINT_FIVE,
            2: serial.STOPBITS_TWO,
        }
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=databits,
                stopbits=stopbits_map.get(stopbits, serial.STOPBITS_ONE),
                parity=parity_map.get(parity, serial.PARITY_NONE),
                timeout=0.05,
            )
            self._running = True
            self._buffer = b""
            self.start()
            self.connection_changed.emit(True)
            return True
        except Exception as e:
            self.error_occurred.emit(f"打开串口失败: {e}")
            return False

    def close_port(self):
        """关闭串口."""
        self._running = False
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._tx_condition.wakeAll()
        self.wait(2000)
        self.connection_changed.emit(False)

    def send_raw(self, data: bytes):
        """发送原始字节数据."""
        self._tx_mutex.lock()
        self._tx_data = data
        self._tx_condition.wakeOne()
        self._tx_mutex.unlock()

    def send_frame(self, cmd: int, data: bytes = b""):
        """按协议封装并发送数据帧."""
        frame = self._protocol.encode(cmd, data)
        self.send_raw(frame)

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open and self._running

    def run(self):
        """线程主循环: 读取串口数据并解析协议帧."""
        while self._running:
            # 处理发送
            self._tx_mutex.lock()
            if self._tx_data is not None:
                data = self._tx_data
                self._tx_data = None
                self._tx_mutex.unlock()
                try:
                    if self._serial and self._serial.is_open:
                        self._serial.write(data)
                except Exception as e:
                    self.error_occurred.emit(f"发送失败: {e}")
            else:
                self._tx_mutex.unlock()

            # 读取数据
            try:
                if self._serial and self._serial.is_open:
                    waiting = self._serial.in_waiting
                    if waiting > 0:
                        raw = self._serial.read(waiting)
                        if raw:
                            self.data_received.emit(raw)
                            self._buffer += raw
                            frames, self._buffer = self._protocol.decode(self._buffer)
                            for frame in frames:
                                self.frame_received.emit(frame)
                    else:
                        self.msleep(5)
                else:
                    break
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"读取错误: {e}")
                break

        self._running = False
