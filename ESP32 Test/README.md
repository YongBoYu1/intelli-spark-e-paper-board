# ESP32-S3 × Waveshare 7.5" e-Paper V2 — Bring-up Notes

成功让墨水屏在 ESP32-S3 上正常工作后的完整记录。

---

## 硬件

| 设备 | 型号 |
|------|------|
| 主控 | SANXIXING ESP32-S3 DevKitC-1（N8R2：8MB Flash + 2MB OPI PSRAM） |
| 墨水屏 | Waveshare 7.5" e-Paper V2（UC8176 控制器，800×480，黑白） |
| 转接板 | Waveshare e-Paper Driver HAT rev2.3 |

---

## 外设总览

| 外设 | 接口 | GPIO |
|------|------|------|
| Waveshare 7.5" e-Paper V2 + Driver HAT rev2.3 | Bit-bang SPI | 4, 11, 12, 14, 21, 47 |
| I2S MEMS 麦克风（NR0562） | I2S | 5, 6, 7 |

---

## 接线一：墨水屏（e-Paper + Driver HAT）

HAT 通过 40-pin 排针与树莓派对接，这里用跳线单独引出各信号。
**HAT 引脚编号 = 树莓派 40-pin 物理引脚编号。**

| 信号 | ESP32-S3 | HAT 物理引脚 | 说明 |
|------|----------|------------|------|
| VCC  | 3V3      | Pin 1      | 逻辑电源 |
| **5V** | **5V（需焊接跳线）** | **Pin 2** | **升压电路电源，必须接！** |
| GND  | GND      | Pin 6      | 共地 |
| DIN  | GPIO 11  | Pin 19     | SPI MOSI |
| CLK  | GPIO 12  | Pin 23     | SPI CLK |
| CS   | GPIO 47  | Pin 24     | SPI CS（低有效） |
| DC   | GPIO 21  | Pin 22     | 数据/命令选择 |
| RST  | GPIO 4   | Pin 11     | 复位（低有效） |
| BUSY | GPIO 14  | Pin 18     | 忙信号 |
| PWR  | 3V3      | Pin 12     | HAT 电源使能 |

### ESP32-S3 5V 输出说明

SANXIXING 板子默认 5V 引脚为**输入**（只接受外部 5V，不输出）。
**需要焊接板上标注位置的短路焊点**，才能让 USB 的 5V 从该引脚输出，为 HAT 供电。

### HAT 40-pin 关键引脚位置

```
Pin  1 [3.3V ← VCC ]  [5V  ← 5V  ] Pin  2
Pin  6 [GND  ← GND ]
Pin 11 [RST  ← GPIO4]  [PWR ← 3V3 ] Pin 12
Pin 18 [BUSY ← GPIO14]
Pin 19 [DIN  ← GPIO11] [GND        ] Pin 20
Pin 21 [MISO*         ] [DC  ← GPIO21] Pin 22   ← *MISO 不连接
Pin 23 [CLK  ← GPIO12] [CS  ← GPIO47] Pin 24
```

---

## 接线二：I2S MEMS 麦克风（NR0562）

圆形小板，6 个引脚，数字 I2S 接口。L/R 直接接 GND（固定左声道，无需占用 GPIO）。

| 麦克风引脚 | 功能 | ESP32-S3 |
|-----------|------|----------|
| VDD  | 电源（3.3V）        | 3V3      |
| GND  | 地                  | GND      |
| SCK  | I2S 位时钟 (BCLK)  | GPIO 5   |
| WS   | I2S 字选择 (LRCLK) | GPIO 6   |
| SD   | I2S 串行数据输出    | GPIO 7   |
| L/R  | 声道选择            | GND（硬接，左声道）|

---

## 踩过的坑

### 1. GPIO 48 = 板载 RGB LED，不能用
RST 最初接在 GPIO48，与板载 RGB LED 共用，导致复位异常。
**修复：RST 改用 GPIO 4。**

### 2. GPIO 35/36 = OPI PSRAM 数据线，不能用
MOSI 和 CLK 最初接在 GPIO35/36，这两个引脚被 2MB OPI PSRAM 占用。
**修复：MOSI 改 GPIO 11，CLK 改 GPIO 12（SPI2 IOMUX 原生引脚）。**

### 3. RST 低电平时间必须约 2ms
- < 1ms：UC8176 不复位
- ≥ 4ms：触发 HAT rev2.3 的电源开关，切断墨水屏供电，BUSY 浮空变 1

`delay(4)` 在 FreeRTOS 下实际可能超过 5ms，**必须用 `delayMicroseconds(2000)`**。

### 4. HAT 必须有 5V 才能工作
HAT 内置升压电路负责生成墨水屏所需的 ±15V 驱动电压，需要 5V 输入（Pin 2/4）。
只接 3.3V（Pin 1/17）时，Power ON（0x04）命令永远无法完成，BUSY 一直为 0。

### 5. 不能发 0x06（Booster Soft Start）
官方 Waveshare 7.5" V2 Python 驱动没有 0x06 这条命令。
发送 0x06 会导致 Power ON 永久卡死（BUSY 始终为 0，超时 10 秒以上）。

### 6. BUSY 极性
| BUSY 电平 | 含义 |
|-----------|------|
| HIGH (1)  | 空闲，可以接受命令 |
| LOW  (0)  | 处理中，等待完成 |

**等待方式：** `while (BUSY == LOW) { delay(100); }`
（与部分旧文档描述相反，以实测为准）

### 7. UC8176 像素编码
| bit 值 | 显示颜色 |
|--------|---------|
| 1      | 黑色    |
| 0      | 白色    |

- 全白：DTM2 全部填 `0x00`
- 全黑：DTM2 全部填 `0xFF`

---

## 初始化序列（UC8176 / 7.5" V2）

```
1. RST: HIGH 200ms → LOW 2ms → HIGH 200ms
2. 等待 BUSY=1（复位后通常已就绪）
3. 0x01 Power Setting:  0x07 0x07 0x3F 0x3F
4. 0x04 Power ON       → 等待 BUSY=1（约 200ms）
5. 0x00 Panel Setting:  0x1F
6. 0x61 Resolution:     0x03 0x20 0x01 0xE0  （800×480）
7. 0x15:                0x00
8. 0x50 VCOM:           0x10 0x07
9. 0x60 TCON:           0x22
10. 0x10 DTM1（旧帧）:   48000 字节  0x00（白）
11. 0x13 DTM2（新帧）:   48000 字节  图像数据
12. 0x12 Display Refresh → 等待 BUSY=1（约 3~15 秒）
13. 0x02 Power Off
```

---

## GPIO 分配总表

```
GPIO  4  → EPD RST
GPIO  5  → MIC SCK  (I2S BCLK)
GPIO  6  → MIC WS   (I2S LRCLK)
GPIO  7  → MIC SD   (I2S Data In)
GPIO 11  → EPD DIN  (SPI MOSI)
GPIO 12  → EPD CLK  (SPI CLK)
GPIO 14  → EPD BUSY
GPIO 21  → EPD DC
GPIO 47  → EPD CS
```

其余 GPIO（1~3, 8~10, 13, 15~20, 22~46）可用于旋转编码器、Wi-Fi 等后续扩展。

---

## 当前实现

`arduino_raw_spi_test/arduino_raw_spi_test.ino`

- 用 bit-bang SPI（软件模拟，~250kHz），绕开硬件 SPI 外设
- 启动时做 GPIO 自检（driveHI / driveLO / pullup / pulldown）
- 按上述序列初始化，显示全黑图案
- BUSY 带超时监控，全程输出到串口（115200 baud）

**下一步：** 切换到硬件 SPI（`SPI.begin()`，可跑 10MHz，速度提升约 40 倍）

---

## 参考文档

| 文件 | 内容 |
|------|------|
| `docs/esp32-s3_datasheet_en.pdf` | ESP32-S3 完整数据手册 |
| `docs/ESP32-S3-inch.pdf` | SANXIXING DevKitC-1 板子引脚图 |
| `docs/NOTE.jpg` | 板子实物引脚标注照片 |
