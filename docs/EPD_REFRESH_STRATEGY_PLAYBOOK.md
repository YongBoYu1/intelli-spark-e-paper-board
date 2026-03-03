# E-Paper Refresh Strategy Playbook (Board Standard)

## 1. 标准声明

本文件是当前板子（Waveshare 7.5" V2, 800x480）唯一生效的刷新标准。

适用范围：
- 运行入口：`tools/run_epaper_console.py`
- 渲染栈：`app/ui/*` + `app/render/refresh_policy.py`
- 页面：Home（kitchen/classic）、Home 内导航 Overlay、Settings、Timer、Weather、Calendar、Menu（兼容路径）

执行原则：
- 新页面与刷新相关改动，必须先对齐本标准。
- 若现场硬件验证结果与本标准冲突，以硬件验证为准，并回写本文件。

---

## 2. 刷新等级

1. `R0_NO_REFRESH`
- 事件未产生可见像素变化，不下发刷新。

2. `R1_PARTIAL_RECT`
- 小面积变化，走局部刷新：`init_part()` + `display_Partial(...)`。
- 所有脏区在提交前做 merge + 8 像素对齐。

3. `R2_FAST_FULL`
- 大面积变化或局刷不满足条件，走快刷整屏：`init_fast()` + `display(...)`（若主题允许）。

4. `R3_FULL_CLEAN`
- 清残影维护或异常恢复，走常规全刷：`init()` + `display(...)`。

---

## 3. 当前板子默认策略（已验证）

### 3.1 全局策略

- 主路径是 `partial-first`：先尝试 `R1`，失败再升级到 `R2/R3`。
- 高频输入启用节流与中间帧丢弃（只保留最新目标态）。
- 局刷区域按 X 方向 8px 对齐，避免边缘脏线。

### 3.2 局刷屏幕白名单

默认白名单：
- `settings,timer,home,menu`

对应主题键：
- `refresh_partial_screens`

### 3.3 Partial 计数预算（已默认关闭）

当前标准：默认关闭“按 partial 次数强制全刷”。

主题键：
- `refresh_partial_budget_enabled: false`

行为说明：
- 关闭后不会因为“第 N 次局刷”触发 `R3_FULL_CLEAN`。
- 仍保留 `full_age`（长期维护）触发条件。

### 3.4 面积门限升级

- 若合并后脏区面积超过页面门限，则从 `R1` 升级到 `R2_FAST_FULL`。
- Home 的 family board 有单独更宽容门限：`refresh_area_limit_home_family_board`。

### 3.5 Fast Full 开关

- 默认：`refresh_enable_fast_full: false`。
- 开启时，`R2` 使用 `init_fast()`，可减轻闪烁但可能增加残影。

---

## 4. Home 页面标准（核心）

### 4.1 导航模式改为 Home 内 Overlay（不换屏）

当前标准不再通过 `home -> menu` 换屏进入导航。

行为：
- 在 `HOME` 长按：切换 `menu_overlay_active`（开/关）。
- `HOME` + overlay 开启时：旋钮移动导航项，点击执行导航项。
- `HOME` + overlay 开启时：`Back` 关闭 overlay。

刷新收益：
- 导航交互保持在 `HOME`，可走纯局部刷新。
- 避免跨页面 `screen_changed` 带来的整屏刷新闪烁。

### 4.2 Home 脏区规则

- 焦点移动：优先行级脏区（`home.focus_move_row`）。
- 左侧面板进出焦点：仅刷新最小指示区（`home.focus_to_left_panel` / `home.focus_from_left_panel`）。
- family board 自动轮播：仅刷新 family board 区。
- 语音条变化：仅刷新 voice overlay 区（不再映射到时钟区）。
- 导航 overlay：
  - 显隐：`home.menu_overlay_toggle`
  - overlay 焦点移动：`home.menu_overlay_focus`

### 4.3 防叠加策略

为避免远距离脏区合并导致大面积刷新：
- 语音活跃时暂停 family board 自动轮播。
- Home overlay 活跃时也暂停 family board 自动轮播。

---

## 5. 语音刷新标准

### 5.1 语音流程渲染

语音流程（recording / processing / done / error）采用 `partial-first`：
- 优先只刷 voice overlay 固定区域（`VOICE_PARTIAL_RECT`）。
- 仅在局刷失败或不支持时回退整屏。

### 5.2 输入防连发

- `Space` 触发语音带冷却窗口（`voice_space_cooldown_s`）。
- 语音活跃期忽略重复 `Space`。
- 每次语音流程后清空 stdin 缓冲，避免连发空格重复触发。

### 5.3 可退出性

- Raw 模式下显式识别 `Ctrl+C`（`\x03`）退出。
- `Q/q` 仍可退出。

---

## 6. 运行时决策顺序

每次状态变化按以下顺序决策：

1. 生成脏区（页面规则 + diff fallback）
2. 节流判定（`min_refresh_gap_ms`）
3. 维护判定（`full_age`；若启用则含 `partial_budget`）
4. 屏幕/旋转变更判定（必要时整屏）
5. 面积门限判定（`R1` 或升级 `R2`）
6. 提交刷新并更新 runtime 计数/时间戳

---

## 7. 标准主题基线（推荐）

`ui_tuner_theme.json` 推荐基线：

```json
{
  "refresh_debug": true,
  "refresh_partial_screens": "settings,timer,home,menu",
  "refresh_mode_menu": "fast",
  "refresh_partial_budget_enabled": false,
  "refresh_area_limit_home": 0.24,
  "refresh_area_limit_home_family_board": 0.30,
  "refresh_enable_fast_full": false,
  "memo_rotate_s": 8,
  "voice_space_cooldown_s": 1.2
}
```

说明：
- `refresh_mode_menu=fast` 用于兼容真正 `Screen.MENU` 路径；Home overlay 路径不依赖该项。

---

## 8. 新页面接入要求（强制）

新增页面必须补齐：

1. 页面分区图（静态区 / 动态区 / 可局刷区）
2. 事件矩阵（事件 -> 脏区 -> 刷新等级）
3. 面积门限与节流参数
4. 失败回退路径（局刷失败 -> 快刷/全刷）
5. 硬件验证记录（日志 + 实拍）

未满足以上项，不得宣称“刷新策略完成”。

---

## 9. 验收口径

以下全部满足才算通过：

- 导航交互无明显整屏闪烁（Home overlay 仅局部刷）。
- 语音状态变化主要为 `VOICE_PARTIAL_RECT`，不应连续整屏刷。
- 高频旋钮下，中间帧可丢弃但最终焦点准确。
- 不因 partial 次数阈值触发全刷（默认配置下）。
- 长时间运行仍可通过 `full_age` 维护恢复画面洁净。

---

## 10. 参考

- Waveshare wiki: [E-Paper Driver HAT Manual](https://www.waveshare.com/wiki/E-Paper_Driver_HAT_Manual)
- 本仓库驱动：`third_party/waveshare_ePaper/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd7in5_V2.py`
- 本仓库策略实现：`app/render/refresh_policy.py` + `tools/run_epaper_console.py`
