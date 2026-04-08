# Issue #61 交接文档 — Calendar（横屏）Python 1:1 对齐（禁止发散）

## 议题关系
- 总任务：#52（**OPEN**）
- 子任务：#61（**只处理 Calendar 横屏**）
- 目标：Calendar 横屏页面按 Python 行为与视觉 **1:1 对齐**，不做主观设计改造。

## 范围定义（仅本 Issue）
1. Calendar 横屏 UI 对齐（结构、字号、权重、间距、模式提示）。
2. Calendar 横屏交互对齐（rotate/click/hold 的行为）。
3. Calendar 横屏刷新策略对齐（dirty reasons/rects/partial-full 决策可解释）。

## 当前主要问题（P0）
- UI 与 Python `app/ui/calendar.py` 存在明显差异（网格与 agenda 区域层级、文本权重/布局不一致）。
- 功能不完整：当前 C++ reducer 中 Calendar 屏 rotate/click 路径缺失，导致“不能 navigate”。
- Calendar 渲染存在占位数据痕迹（静态 agenda 行），与 Python 基于模型数据渲染不一致。

## 硬约束
1. Python 行为是硬指标（source-of-truth）。
2. 不修改 `third_party/waveshare_ePaper`。
3. 不混入 setting/weather/timer/memo/list 的改动。
4. 保留可 debug 日志：dirty reasons、rects、mode、refresh 决策。
5. 继续在 `codex/52-runtime-migration` 工作。

## Python 对齐基线（必须逐项参照）
- `app/ui/calendar.py`
- `app/core/reducer.py`（`calendar_mode/calendar_offset_days/calendar_selected_index`）
- `app/render/refresh_policy.py`（calendar dirty 推导与 partial/full 路径）

## C++ 对应文件
- `firmware/main/ui/screens/calendar_screen.cpp`
- `firmware/main/ui/screens/calendar_screen_landscape.cpp`
- `firmware/main/app/reducer.cpp`
- `firmware/main/app/runtime.cpp`
- （必要时）`firmware/main/ui/render_app.cpp`

## 语义对齐合同（必须满足）
1. rotate：
   - `date` 模式下调整 `calendar_offset_days`；
   - `agenda` 模式下在 agenda items 内移动 `calendar_selected_index`。
2. click：
   - `date` 模式进入 `agenda` 模式；
   - `agenda` 模式对 reminder 项执行 toggle（事件项不 toggle），无可选项时回退日期模式逻辑与 Python 一致。
3. hold/back：
   - 返回 Home 的行为与 Python 一致。
4. 渲染：
   - 左侧月历网格、右侧当天 agenda、空态文案、footer 提示与 Python 对齐。
5. 数据来源：
   - agenda 行来自 state/model，不允许静态硬编码占位内容替代真实路径。

## 执行顺序（按序）
1. 先做 Python->C++ 对照表（函数级）：
   - reducer calendar 事件处理
   - UI 渲染结构映射
   - refresh reason/rect 映射
2. 补齐 reducer 的 Calendar rotate/click 语义。
3. 清除横屏 calendar 的静态占位 agenda 渲染，改为模型驱动。
4. 对齐 UI 字体/字号/间距（仅按 Python，不做主观微调）。
5. 对齐 refresh dirty reasons 与 rect 覆盖范围。
6. 实机回归并附日志。

## 实机回归场景
1. Calendar 横屏 date 模式连续 rotate 30 次，检查日期游标与网格高亮一致。
2. click 进入 agenda，再 rotate 移动焦点，检查选中逻辑稳定。
3. agenda 模式 click 对 reminder toggle，检查状态变化与日志可追溯。
4. 无 agenda 项日期下的空态与提示文案与 Python 一致。
5. 全过程不得出现无法解释的全刷与残影。

## 验收标准
- 横屏 Calendar 视觉与交互达到 Python 1:1（以实机为准）。
- reducer 中 Calendar 的 rotate/click 语义完整可用。
- refresh 日志可解释每次决策，不再黑盒。

## 非目标
- 竖屏 Calendar（后续单独 issue）。
- Setting 功能对齐（后续单独 issue）。
- 真实天气/温度/时间数据接入（后续单独 issue）。
