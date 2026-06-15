# JkeyToys

PySide6 UART 上位机调试工具，通过自定义帧协议与嵌入式下位机串口通信。

## 文件结构

```
core/                    后端（零 UI 依赖）
  crc.py                 CRC 校验算法
  protocol_config.py     协议帧格式配置（ProtocolConfig 数据类）
  protocol.py            帧协议编解码（Protocol 实例化）
  serial_worker.py       串口读写线程（SerialWorker QThread）

ui/                      界面
  main_window.py         主窗口，串联所有模块，管理 protocol/ 目录读写
  serial_panel.py        串口配置面板
  data_panel.py          数据收发面板（纯 HEX/ASCII）
  protocol_panel.py      命令调试面板（命令按钮、自动匹配响应/上报、字段解析显示）
  protocol_editor.py     命令清单编辑器（含字段编辑弹窗）
  protocol_settings_dialog.py  协议帧格式配置对话框

protocol/                协议配置
  protocol.json          用户协议配置（运行时生成，导入导出默认目录）
  protocol_default.json  出厂默认协议模板

tools/                   测试与模拟
  virtual_device.py      虚拟下位机，读取 protocol.json 模拟设备响应 + 定时上报
  virtual_pair.py        内存管道自测（单进程，不依赖串口驱动）
  test_serial.py         端到端串口测试（需已配对的虚拟串口 COM2/COM3）
```

## 数据流

```
MainWindow 持有 Protocol + SerialWorker，管理 protocol.json

SerialPanel ──open/close──> MainWindow ──> SerialWorker
DataPanel ──send_raw──> MainWindow ──> SerialWorker
ProtocolPanel ──send_frame──> MainWindow ──> SerialWorker

SerialWorker ──data_received──> DataPanel（原始显示）
SerialWorker ──frame_received──> ProtocolPanel（自动匹配 pending 命令）
SerialWorker ──error/connection──> StatusBar + DataPanel
```

## 协议格式

默认帧格式（可通过「协议 → 协议配置」自定义）：

```
帧头 | CMD | LEN | DATA | XOR | 帧尾
AA555AA5 | 2B  | 2B  | NB   | 1B  | 0D0AA55A
```

- LEN 表示 LEN 字段后到校验前的字节数（即 DATA 长度）
- CMD 位置可选：LEN 之前（默认）或 LEN 之后（此时 LEN = CMD+DATA）
- 校验支持 XOR（默认）/ CRC16-MODBUS / CRC16-CCITT / CRC32 / 无
- 字节序默认小端（little-endian），可配置

## 命令配置

每条命令定义在 `protocol.json` 中，包含：
- `type`: 下发（可发送，等待回包）或 上报（仅接收识别）
- `tx_fields` / `rx_fields`: 发送/接收数据的字段拆分（名称+字节大小）
- `tx_data_len` / `rx_data_len`: 从字段大小自动计算，用于收发校验

下发命令支持多条并发发送，每条独立超时计时。

## 设计原则

- **core/ 不导入 PySide6**：后端可独立测试
- **protocol/ 目录统一管理**：`protocol_default.json` 是出厂模板，`protocol.json` 是用户数据（首次启动自动复制）；导入导出对话框默认打开此目录
- **MainWindow 统一管理文件 I/O**：面板通过信号通知 MainWindow 保存
- **信号传递原始 bytes/Frame**：UI 层负责格式化显示

## 开发约定

- 中文 docstring，`from __future__ import annotations`
- core/ 下不导入 PySide6

## 命令

```bash
python main.py                              # 启动上位机
pip install -r requirements.txt             # 安装依赖
python tools/virtual_device.py COM3 115200  # 启动虚拟下位机
python tools/virtual_device.py COM3 115200 --report 5  # 带定时上报
python tools/virtual_pair.py --self-test    # 内存管道自测
python tools/test_serial.py                 # 端到端串口测试
```

## 依赖

Python >= 3.10，PySide6 >= 6.5.0，pyserial >= 3.5
