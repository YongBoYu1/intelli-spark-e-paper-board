# E-Paper Refresh Strategy Playbook (Issue #18)

## 1. 目标

解决当前「任意动作都会触发全局刷新」问题，并沉淀一套可复用刷新策略，供后续所有 UI 页面设计直接套用。

适用范围：
- 本仓库当前板型与驱动：`waveshare_epd.epd7in5_V2`（`800x480`，黑白屏）。
- 运行路径：`tools/run_epaper_console.py` + `app/ui/*` 渲染栈。
- 页面：Home（kitchen/classic）、Menu、Weather、Calendar、Settings。

---

## 2. 板型与官方能力边界（必须先确认）

### 2.1 当前代码确认到的板型

- 驱动加载固定为 `epd7in5_V2`：`app/render/epd.py`
- 驱动分辨率：`EPD_WIDTH=800`, `EPD_HEIGHT=480`：`third_party/waveshare_ePaper/.../epd7in5_V2.py`
- 驱动提供三类初始化：
  - `init()`：常规全刷
  - `init_fast()`：快刷
  - `init_part()` + `display_Partial(...)`：局刷

### 2.2 官方资料关键约束（Waveshare）

1. 7.5" V2 新旧批次差异  
根据 Waveshare 官方 wiki FAQ：`7.5inch e-Paper V2` 在 2023 年 9 月前后存在版本差异，新版本使用 V2 程序，旧版本可能无法用新程序。  

2. 刷新时延（官方参数）  
Waveshare 官方 wiki（7.5" V2 对应参数）给出：
- Full refresh time: `~4s`
- Partial refresh time: `~0.4s`
- Fast refresh time: `~1.5s`

3. 使用限制（官方注意事项）  
Waveshare 官方 wiki 建议：
- 刷新间隔不小于 `180s`（针对“同一画面长时间静态场景”的维护建议）
- 每次进入休眠前应清屏
- 长期运行建议至少 `24h` 全刷一次，避免残影累积

4. 局刷轮次建议（官方 FAQ）  
Waveshare FAQ 给出保守建议：局刷约 `5` 轮后执行一次全刷，避免残影积累。

### 2.3 实战含义

- 不可把“局刷”当作无限次能力使用，必须设计“局刷预算 + 强制全刷回收”。
- 必须支持能力退化：若板子批次或实测不稳定，自动回退到快刷/全刷。

---

## 3. 当前项目问题诊断（针对本仓库）

### 3.1 现状

`tools/run_epaper_console.py` 当前渲染路径：
- `_render_to_epd(...)` 内部最终调用 `display_image(...)`
- `display_image(...)` 直接走 `epd.display(...)`（整屏）
- 文件内注释明确写了“目前先全刷，局刷后续再加”

结论：当前任意状态变化，只要触发重渲染，就会整屏刷新。

### 3.2 直接后果

- 闪烁重
- 输入反馈慢（旋钮移动、焦点切换也触发整屏）
- 功耗上升
- 残影风险更难控（大量不必要全局波形）

---

## 4. 刷新策略总设计

采用四级刷新策略，不再单一“整屏刷新”。

### 4.1 刷新等级定义

1. `R0_NO_REFRESH`
- 事件不引起可见像素变化
- 不下发任何 EPD 刷新

2. `R1_PARTIAL_RECT`
- 小范围局部变化（焦点、单行数据、时间数字）
- 使用 `init_part()` + `display_Partial(...)`
- 支持多脏区合并后一次提交

3. `R2_FAST_FULL_SCREEN`
- 页面内容大幅变化但可接受快刷残影（如页面切换、整卡片重排）
- 使用 `init_fast()` + `display(...)`

4. `R3_FULL_CLEAN`
- 强制消残影或异常恢复
- 使用 `init()` + `display(...)`，必要时 `Clear()`

### 4.2 选择原则（决策顺序）

1. 能否不刷新：若像素无变化则 `R0`
2. 能否局刷：若仅涉及有限区域且批次支持局刷则 `R1`
3. 是否整页变化：整页变化优先 `R2`
4. 是否到达维护阈值：满足任一条件升级到 `R3`

### 4.3 强制全刷触发条件（建议默认）

满足任一条件直接 `R3_FULL_CLEAN`：
- `partial_count >= full_refresh_every`（策略参数）
- 距上次全刷超过 `24h`
- 连续局刷出现明显残影/错位（人工标记或检测）
- 从局刷模式切回全刷模式（驱动状态切换边界）
- 异常恢复（SPI 异常、busy 超时、显示错帧）

---

## 5. 脏区策略（Dirty Rect）

### 5.1 脏区生成

页面渲染层按“组件区块”输出脏区，不做逐像素 diff。

每次事件：
- 记录受影响区块矩形
- 对矩形做 union/merge（重叠合并）
- 最后一次性提交 1~N 个局刷任务（通常建议 1~3 个）

### 5.2 8 像素对齐（必须）

`epd7in5_V2.display_Partial(...)` 以字节对齐处理 X 坐标，所有脏区都要：
- `x0` 向下对齐到 8 的倍数
- `x1` 向上对齐到 8 的倍数

否则容易出现错位、边缘脏线、局刷区域异常。

### 5.3 刷新节流

建议：
- `min_refresh_gap_ms = 120`（同一时段高频事件合并）
- 高频旋钮事件只刷新“最终焦点态”，中间帧可丢弃
- Tick 驱动（秒钟/倒计时）也走同一节流队列

---

## 6. 页面级实战矩阵（本项目内容）

下面策略基于当前页面内容结构：  
Home（左侧时钟/天气+右侧列表）、Menu、Weather、Calendar、Settings。

### 6.1 Home（kitchen 变体，默认）

建议区块拆分：
- `H_LEFT_CLOCK`：时间/日期/语音覆盖层
- `H_LEFT_MEMO`：左侧 memo 文本区
- `H_LEFT_WEATHER_STRIP`：左下天气条
- `H_RIGHT_LIST`：右侧 fridge + shopping 列表主体
- `H_RIGHT_FOCUS_ROW`：当前焦点行

事件到刷新建议：
- 旋钮换焦点（同页）  
  优先 `R1`，只刷“旧焦点行 + 新焦点行”或最小包围框
- 秒钟更新时间（时钟模式）  
  `R1`，只刷 `H_LEFT_CLOCK` 的数字区
- 天气数据后台更新  
  `R1`，刷 `H_LEFT_WEATHER_STRIP`（必要时附带右侧统计区）
- 勾选任务（无重排）  
  `R1`，刷单行 checkbox + 文本
- 延迟 2s 触发重排  
  可选 `R2`（刷右半屏更稳）；若残影可控可用 `R1` 刷 `H_RIGHT_LIST`
- 进入/退出语音覆盖  
  `R1`，刷 `H_LEFT_CLOCK` 覆盖区域
- Home <-> 其他页面切换  
  `R2`（快刷整屏），避免复杂跨页脏区管理

### 6.2 Menu

建议区块：
- `M_PILLS_ROW`：中间菜单 pill 行

事件：
- 旋钮切换菜单项：`R1` 刷 `M_PILLS_ROW`
- 进入菜单/退出菜单：`R2` 整屏快刷

### 6.3 Weather Detail

建议区块：
- `W_HERO`：顶部主温度和天气描述
- `W_METRICS`：湿度/体感/风速
- `W_FORECAST_ROW`：底部 forecast 行

事件：
- 日索引切换：优先 `R1` 刷 `W_HERO + W_METRICS + W_FORECAST_ROW`
- 首次进入页面：`R2`
- 数据全量更新：`R2`（优先稳定）

### 6.4 Calendar Detail

建议区块：
- `C_LEFT_GRID`：月历网格
- `C_RIGHT_HEADER`
- `C_RIGHT_AGENDA`

事件：
- 日期偏移变化：`R1` 刷 `C_LEFT_GRID + C_RIGHT_HEADER + C_RIGHT_AGENDA`
- agenda 光标移动：`R1` 只刷 `C_RIGHT_AGENDA` 当前/上一项
- 页面进入/退出：`R2`

### 6.5 Settings

建议区块：
- `S_LIST_ROWS`
- `S_FOOTER`（状态提示 + last sync）

事件：
- 旋钮移动焦点：`R1` 刷“前后两行”
- 点击切换值：`R1` 刷当前行
- `SYNC_NOW` / notice timeout：`R1` 刷 `S_FOOTER`
- 旋转角度切换 0/180：`R2`（整屏重绘更稳）

---

## 7. 参数模板（Slow / Balanced / Fast）

建议将 `partial_refresh_mode` 映射为明确策略参数：

| 模式 | `full_refresh_every` | `min_refresh_gap_ms` | 适用 |
|---|---:|---:|---|
| `slow` | 5 | 200 | 保守，最低残影 |
| `balanced` | 10 | 120 | 默认推荐 |
| `fast` | 15 | 80 | 交互优先 |

补充：
- 现有设置项中的 `20` 可保留，但不建议默认；先以 `10/15` 为主。
- 若现场屏幕残影敏感，直接降档到 `slow`。

---

## 8. 运行时状态机（建议实现）

维护以下刷新状态：
- `supports_partial: bool`
- `partial_count: int`
- `last_full_refresh_ts: float`
- `last_refresh_ts: float`
- `pending_dirty_rects: list[Rect]`

建议伪代码：

```text
on_event(event):
  dirty = map_event_to_dirty(event, screen, state_before, state_after)
  if dirty.empty:
    return
  enqueue(dirty)

flush():
  if now - last_refresh_ts < min_refresh_gap_ms:
    return
  rect = merge_and_align8(pending_dirty_rects)

  if must_full_refresh():
    epd.init()
    epd.display(full_frame)
    partial_count = 0
    last_full_refresh_ts = now
  else if supports_partial and rect.is_local():
    epd.init_part_if_needed()
    epd.display_Partial(full_frame_buffer, rect.x0, rect.y0, rect.x1, rect.y1)
    partial_count += 1
  else:
    epd.init_fast()
    epd.display(full_frame)

  last_refresh_ts = now
  clear_pending_rects()
```

---

## 9. 新页面接入模板（以后直接照这个做）

每新增一个 UI 页面，必须补齐以下 6 项：

1. 页面区块图  
列出静态区、动态区、可局刷区（矩形坐标）

2. 事件矩阵  
列出“事件 -> 影响区 -> 刷新等级（R0/R1/R2/R3）”

3. 模式参数  
slow/balanced/fast 对应阈值

4. 强制全刷规则  
局刷计数、定时维护、异常恢复规则

5. 回退策略  
局刷失败时如何退回快刷/全刷

6. 验证记录  
按第 10 节 checklist 记录结果

---

## 10. 验证 Checklist（实战验收）

### 10.1 功能正确性

- 焦点移动只刷新必要区域，不再整屏闪烁
- 页面切换稳定，无黑块/残缺/错位
- 局刷边界无明显脏线（8px 对齐生效）

### 10.2 体验指标

- 交互延迟（旋钮到可见变化）目标 `< 200ms`
- Home 秒钟更新不影响右侧列表
- 高频旋钮下无明显连闪

### 10.3 画质与寿命

- 连续局刷 `N` 次后触发全刷可有效清残影
- 连续运行 24h 后仍可恢复到干净状态
- 睡眠前执行清理流程（按官方建议）

### 10.4 异常场景

- busy 超时可恢复
- SPI 短故障后可回退全刷
- 局刷不可用时自动降级（不阻塞交互）

---

## 11. 对当前代码的最小改造建议

优先级按从快到慢：

1. 把 `tools/run_epaper_console.py` 的 `_render_to_epd(...)` 从“仅全刷”升级为“策略调度入口”
2. 新增 `app/render/refresh_policy.py`（或同等模块）维护状态机和阈值
3. 在 `app/ui/*` 增加页面级脏区定义（先做 Home + Settings）
4. 接入 `partial_refresh_mode` / `full_refresh_every` 到真实策略，而不是仅显示
5. 增加一份硬件回归脚本：焦点移动、秒钟更新、任务勾选、跨页切换

---

## 12. 参考资料（官方）

- Waveshare wiki: [E-Paper Driver HAT Manual](https://www.waveshare.com/wiki/E-Paper_Driver_HAT_Manual)
- Waveshare wiki FAQ（同页）: 7.5 V2 新旧版本差异、局刷轮次建议、维护建议
- Waveshare product: [7.5inch e-Paper HAT](https://www.waveshare.com/7.5inch-e-paper-hat.htm)
- Waveshare product: [7.5inch e-Paper HAT (H)](https://www.waveshare.com/7.5inch-e-paper-hat-h.htm)
- 本仓库驱动实现：`third_party/waveshare_ePaper/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd7in5_V2.py`

