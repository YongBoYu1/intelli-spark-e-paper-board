# Issue #63 交接文档 — Home 竖屏 Python 1:1 迁移（禁止发散）

## 目标定义
- 当前阶段只做一件事：`Home 竖屏` 严格按 Python 行为迁移到 C++。
- 规则：先对齐，再谈优化；禁止新增主观 UX/策略。
- 必须满足：
  1. Home 竖屏 UI 与 Python 1:1。
  2. Home 竖屏交互与 Python 1:1（focus/rotate/click/long-press/back）。
  3. Home 竖屏 refresh reason/rect 与 Python 1:1。

## 当前代码现状（已核对）

### 已接上的部分
1. Home 渲染入口已按 `settings.rotation_deg` 切换 portrait：
   - `firmware/main/ui/screens/home_screen.cpp` 中 `render_home_bitmap()` 已在 90/270 走 `render_home_portrait_bitmap()`。
2. Home 导航覆盖层交互路径已存在：
   - `LongPress` / `Back` 可在 Home 打开或关闭 menu overlay（`reducer.cpp`）。
   - overlay 下 rotate 可移动 menu focus，click 可进入 Memo/List/Timer/Calendar/Settings。
3. Settings 里 `Rotation` 项会循环 0/90/180/270，影响全局 `state.settings.rotation_deg`。

### 关键缺口（P0）
1. **Home dirty plan 仍是 landscape 坐标语义**：
   - `home_dirty_plan()` 仍使用 `home_landscape_metrics()` 及其 rect helper。
   - 对竖屏 Home 来说，partial refresh 的 rect/reason 覆盖存在错位风险（残影、漏刷、异常全刷）。
2. **Home portrait 与 Python 的 1:1 对齐仍不完整**：
   - 当前 portrait 实现是 C++自建像素绘制管线，需逐项核对 Python `home_kitchen_portrait.py` 的字号/层级/间距/焦点表现。
3. **“Home->Navigation->Settings->Rotation->回Home”链路缺少对齐验证**：
   - 代码通路在，但尚未作为正式验收路径跑通并固化标准。

## Python 对齐基线（Home）
- `app/ui/home_kitchen.py`
- `app/ui/home_kitchen_portrait.py`
- `app/core/reducer.py`（Home/menu overlay/focus/rotate/click）
- `app/render/refresh_policy.py`（Home portrait/landscape dirty reason 与 rect）

## C++ 重点文件
- `firmware/main/ui/screens/home_screen.cpp`
- `firmware/main/ui/screens/home_screen_portrait.cpp`
- `firmware/main/ui/screens/home_screen.hpp`
- `firmware/main/app/reducer.cpp`
- `firmware/main/app/runtime.cpp`
- `firmware/main/ui/render_app.cpp`
- （链路依赖）`firmware/main/ui/screens/settings_screen.cpp`

## 执行顺序（只做对齐）

1. 先做 Home parity 对照表（函数级）
   - Python Home 渲染结构 -> C++ portrait/landscape 渲染映射。
   - Python reducer Home 交互 -> C++ reducer 映射。
   - Python refresh policy Home reasons/rects -> C++ Home dirty plan 映射。

2. 先修 Home refresh 对齐（优先级最高）
   - 在 `HomeDirtySnapshot` 显式纳入布局/旋转维度（至少能区分 portrait/landscape）。
   - `home_dirty_plan()` 分支出 portrait rect 规则，禁止用 landscape rect 直接套竖屏。
   - reason 名称与 Python 保持一致（`home.focus_* / home.clock_or_timer_state / home.weather_update / home.reminder_* / home.family_board_update / home.menu_overlay_*`）。

3. 对齐 Home 交互闭环
   - Home 常态 rotate：焦点流转正确。
   - Home click：clock/weather/list item 的行为与 Python 一致。
   - Home long-press/back：navigation overlay 的开关、rotate、click 行为一致。

4. 对齐“横竖切换入口”链路（基于 Home）
   - 从 Home 呼出 navigation -> 进入 Settings -> 选中 Rotation -> click 切换。
   - 切换后返回 Home，验证 portrait 渲染 + 交互 + refresh 全部正常。

5. 最后做 Home 视觉细节 1:1
   - 只按 Python 对齐，不做主观重设计。
   - 字体权重、字号、间距、焦点下划线/边框、天气区与 family board 排布逐项对齐。

## 实机验收（必须通过）
1. Home 竖屏连续 rotate 30 次（含左右区切换），无异常全刷和残影。
2. Home 竖屏下 inventory/reminder 的 focus 与 click 反馈稳定，状态可恢复。
3. Home 中 long-press 呼出 navigation，rotate 选择 Settings，click 进入成功。
4. Settings 中 click Rotation 后回 Home，方向切换生效且 UI/交互正常。
5. 日志可解释每次 refresh 决策（reason/rect/mode/R1-R3）。

## 验收标准
- Home 竖屏在 UI、交互、refresh 三方面达到 Python 1:1。
- Home->Navigation->Settings->Rotation->Home 链路按 Python 行为稳定复现。
- 不引入新 heuristic，不修改 `third_party/waveshare_ePaper`。

## 非目标
- 本阶段不收 Calendar/Settings 全页面的视觉细节（只保留 Home 链路所需最低依赖）。
- 实时天气/温度/时间数据链路归 #62，不在本文件收口。

## 2026-04-08 实施进展（本轮）

### 已完成（代码已落地）
1. Home 竖屏渲染补齐交互可视反馈：
   - 竖屏 Home 新增 focus 可视化（clock/weather/row）。
   - 竖屏 Home 新增 navigation menu overlay 绘制（含 focus pill 高亮）。
   - 竖屏列表改为使用可见索引（含 hidden 过滤），不再直接画全量原始数组。
2. Home 竖屏交互映射修复：
   - reducer 中 Home inventory 可见行数改为按旋转维度区分：landscape=3，portrait=4。
   - 使 focus/click 与竖屏实际可见行一致。
   - reducer 对齐 Python Home 语义：
     - `clock + widget_mode=Timer + click`：从 Home 进入 Timer 页面（不再在 Home 直接 start/pause）。
     - `Home + back + clock focus + widget_mode=Timer`：取消 timer 并回到 clock widget（不打开 overlay）。
3. Home refresh parity 核心修复：
   - `HomeDirtySnapshot` 新增 `rotation_deg` / `portrait_layout`。
   - `home_dirty_plan()` 按 layout 分支 portrait/landscape rect 规则，竖屏不再复用 landscape rect。
   - Home reasons 补齐 `home.reminder_change_fallback` 并保持 `home.*` 命名体系。
4. 构建验证：
   - `cmake --build build -j4 --target __idf_main` 编译通过（含 `reducer.cpp` 最新改动）。

### 仍需继续对齐（下一轮）
1. Home 竖屏视觉细节仍需逐项按 Python 1:1 收敛（字体权重/字号/间距、局部微调）。
2. 按验收路径完成实机回归并记录日志样本（R1/R2/R3 + reason/rect）。
