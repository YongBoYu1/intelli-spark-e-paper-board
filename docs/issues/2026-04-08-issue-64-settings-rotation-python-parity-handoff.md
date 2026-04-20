# Issue #64 交接文档 — Settings Rotation Python 1:1 对齐（禁止发散）

## 背景与目标
- `Home` 竖屏链路本轮先收尾，下一上下文只做 `Settings + Rotation` 对齐。
- 目标：`Settings` 在旋转前后的行为与 Python 一致。
- 规则：先对齐，再优化；禁止新增主观 UX。

## Python 基线结论（已确认）
1. 点击 Settings 的 `Rotation` 只会切换角度，不会切屏。
   - `app/core/reducer.py` -> `_handle_settings_click()` / `_toggle_rotation()`
2. 旋转后仍停留在 `Settings`，由 app 层统一做画布旋转。
   - `app/ui/settings.py` 只有一套 `render_settings()`
   - `app/ui/app.py` 在 `render_app()` 里统一按 `rotation_deg` 旋转画布

## C++ 当前现状（已核对）
1. reducer 行为层面与 Python一致：
   - `Rotation` 点击只更新 `state.settings.rotation_deg`，不改 `state.screen`。
   - 文件：`firmware/main/app/reducer.cpp`
2. 视觉层面与 Python不一致：
   - C++ 目前是两套 Settings renderer：
     - `render_settings_landscape_bitmap()`
     - `render_settings_portrait_bitmap()`
   - `render_settings_bitmap()` 按 90/270 直接切到 portrait renderer。
   - 文件：
     - `firmware/main/ui/screens/settings_screen.cpp`
     - `firmware/main/ui/screens/settings_screen_landscape.cpp`
     - `firmware/main/ui/screens/settings_screen_portrait.cpp`
3. 结果：
   - 旋转后仍在 Settings（行为对）
   - 但 UI 切成“另一套页面风格”（与 Python 单一 renderer 结果不一致）

## P0 问题定义
1. **Settings 存在双 renderer 分叉**，导致 rotation 后出现“第二套 Settings 页面”。
2. **Python 是单 renderer + 全局旋转**，C++ 当前实现语义不等价。
3. 需要把 C++ Settings 收敛到 Python 语义：**同一套 Settings 逻辑在不同旋转下呈现，不出现独立风格分叉。**

## 对齐范围（本 Issue 内）
1. Settings 页面 UI 结构/字体/布局对齐 Python（0/90/180/270）。
2. Settings 页面交互对齐 Python（rotate/click/back/long-press）。
3. Rotation 项链路对齐：
   - Home -> Navigation -> Settings -> Rotation(click) -> 仍在 Settings（旋转后样式仍是 Python 同源结构）。

## 明确非目标
1. 不在本 Issue 内做 Home 新需求（Home 视为已收尾，仅回归依赖链路）。
2. 不扩展 Settings 新功能（仅对齐已有项）。
3. 不改 `third_party/waveshare_ePaper`。

## 重点代码文件
- C++：
  - `firmware/main/ui/screens/settings_screen.cpp`
  - `firmware/main/ui/screens/settings_screen_landscape.cpp`
  - `firmware/main/ui/screens/settings_screen_portrait.cpp`
  - `firmware/main/app/reducer.cpp`
  - `firmware/main/ui/render_app.cpp`
- Python 基线：
  - `app/ui/settings.py`
  - `app/ui/app.py`
  - `app/core/reducer.py`
  - `app/core/settings_schema.py`

## 执行顺序（只做对齐）
1. 先做 parity 对照表（函数级）
   - Python `render_settings()` 与 C++ landscape/portrait 映射差异逐条列出。
   - Python reducer Settings 交互与 C++ reducer 对照。
2. 收敛渲染架构（P0）
   - 去掉“视觉风格分叉”路径（不再出现独立 card 风格 portrait Settings）。
   - 保持 0/90/180/270 下均来自同源 Settings 布局语义。
3. 对齐 Rotation 交互链路
   - 点击 Rotation 后保留在 Settings。
   - 旋转后 focus/条目/value 文案位置与 Python一致。
4. 最后做细节 1:1
   - 字号、字重、间距、divider、footer notice、focus 下划线对齐 Python。

## 验收用例（必须通过）
1. 在 Settings 连续点击 Rotation（0->90->180->270->0）时：
   - 始终停留在 Settings；
   - 不出现“第二套风格页面切换感”。
2. Settings 下 rotate/click/back/long-press 行为与 Python 一致。
3. 从 Home 进入 Navigation -> Settings -> Rotation，链路稳定可复现。
4. 日志能解释刷新决策（mode + reason + rect + R1/R2/R3）。

## 验收标准
- Settings rotation 行为与 Python 1:1。
- Settings 在各旋转角度下为同源 UI 语义，不再出现 C++ 特有分叉页面。
- 不引入新 heuristic。

## 备注（给下一上下文）
- 本次已经确认：用户期望与 Python 一致为“旋转后仍在 Settings”，不是“自动回 Home”。
- 现象根因已锁定在 `settings_screen.cpp` 的 portrait/landscape 双 renderer 分支，不在 reducer。
