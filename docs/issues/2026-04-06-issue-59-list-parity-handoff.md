# Issue #59 交接文档 — List/Home 联动（产品语义收敛）

## 议题关系
- 总任务：#52（**OPEN**，尚未收尾）
- 子任务：#59（**只处理 List + Home 联动**）
- 目标：List 页行为与 Home 联动行为在 ESP32 端收敛到一致、可解释、可量产的产品语义。

## 问题定义（P0）
- 当前实机现象：
  - 在 List（inventory/reminder）里 check 后，Home 能先看到对应项被勾选；
  - 过一段时间后 Home 可能触发全刷，出现条目“消失/状态不一致”的感知。
- 本 Issue 要做的是把这条链路在 C++ 端收口，并能用日志解释每一步。

## 硬约束
1. Python 作为迁移参考基线；产品语义以 C++ 量产行为为准，并在文档中显式记录偏差。
2. 不修改 `third_party/waveshare_ePaper`。
3. 不混入 timer/memo/settings 等其它页面改动。
4. 保留可读日志：dirty reasons / rects / mode / refresh decision。
5. 除非用户明确要求，所有工作继续在 `codex/52-runtime-migration`。

## Python 参考基线（用于迁移对照）
- `app/ui/list_unified.py`
- `app/ui/home_kitchen.py`
- `app/core/reducer.py`
- `app/render/refresh_policy.py`

## C++ 对应文件
- `firmware/main/ui/screens/list_screen.cpp`
- `firmware/main/ui/screens/list_screen_landscape.cpp`
- `firmware/main/ui/screens/list_screen_portrait.cpp`
- `firmware/main/ui/screens/home_screen.cpp`
- `firmware/main/app/reducer.cpp`
- `firmware/main/app/runtime.cpp`

## Python -> C++ 对照表（仅 List/Home 联动）
| Python 语义 | Python 位置 | C++ 位置 | 对齐状态 |
| --- | --- | --- | --- |
| List toggle: 切换 completed + delayed reorder + uncheck 恢复 visibility tracking | `app/core/reducer.py::_toggle_task_completed_by_index` | `firmware/main/app/reducer.cpp` (`Screen::Inventory` click 分支) | ⚠️ **有意产品偏差**：在 C++ 中 reminder/inventory 的 completed 都进入 pending-hide（与 Home 一致） |
| Home toggle: 切换 completed + pending-hide grace + delayed reorder | `app/core/reducer.py::_toggle_home_kitchen_task_by_index` | `firmware/main/app/reducer.cpp` (`HomeFocusTargetKind::ReminderItem` 分支) | ✅ 已对齐 |
| hide promotion: grace + settle 到期后 pending -> hidden | `app/core/reducer.py::_maybe_promote_home_pending_hide` | `firmware/main/app/reducer.cpp` (`handle_tick`) | ✅ 已对齐 |
| reorder apply: 到期后 stable sort + 清 pending_reorder | `app/core/reducer.py::_apply_reorder` | `firmware/main/app/reducer.cpp::apply_reminder_reorder` | ✅ 已对齐 |
| Home dirty reason: row_update / reorder / compact 三分支 | `app/render/refresh_policy.py` | `firmware/main/ui/screens/home_screen.cpp::home_dirty_plan` | ✅ 已补齐 `home.reminder_reorder` |
| rect 语义：reorder=分区 targeted，compact=较大 list 区域 | `app/render/refresh_policy.py` | `firmware/main/ui/screens/home_screen.cpp` | ✅ 已对齐 |
| refresh 决策日志：reason+rects+R1/R2/R3 | `app/render/refresh_policy.py` + runtime | `firmware/main/app/runtime.cpp` | ✅ 已增强（R2 增加 rects） |

## 迁移语义合同（含产品覆盖）
1. **List toggle 路径**（`_toggle_task_completed_by_index`）：
   - 切换 completed 状态；
   - 进入 delayed reorder（`pending_reorder` / `reorder_due_at`）；
   - uncheck 时恢复 visibility tracking；
   - 产品覆盖：C++ 侧 reminder/inventory 在 completed 时都进入 pending-hide（与 Home 统一）。
2. **Home toggle 路径**（`_toggle_home_kitchen_task_by_index`）：
   - 切换 completed；
   - completed 项进入 pending-hide grace（`home_pending_hide_rids`）；
   - 同样进入 delayed reorder；
   - hide promotion 必须按 grace/settle 规则触发。
3. **Home 列表刷新 reason**：
   - `home.reminder_row_update`
   - `home.reminder_reorder`
   - `home.reminder_compact`
   - rect 选择必须跟 reason 语义走，不能用兜底大框混过去。

## 产品语义决策（2026-04-06）
- 决策：List/Home 对 reminder 与 inventory 执行 check 时，统一进入 pending-hide grace（10s）并在 settle 后 promotion 到 hidden。
- 原因：用户感知一致性优先，避免“Home 点击会消失、List 点击不会消失”的双重规则。
- 影响：该行为相对 Python 参考实现存在有意偏差；Python 不再作为后续改动约束源。

## 当前差距（函数级）
- `firmware/main/app/reducer.cpp`
  - ✅ 已补链路日志：source / pending-hide / hidden / reorder schedule&apply / hide promote。
- `firmware/main/ui/screens/home_screen.cpp`
  - ✅ 已补齐 `home.reminder_reorder`，并区分 reorder 与 compact 的 rect 作用域。
- `firmware/main/app/runtime.cpp`
  - ✅ partial reinforce 已覆盖 row_update/reorder/compact；
  - ✅ `R2_FAST_FULL` 日志已带 rects，便于解释 area gate 决策。

## 执行顺序（必须按序）
1. 先做 reducer + dirty plan 的 Python->C++ 对照表（仅 List/Home 联动）。
2. 在 Home dirty reason 中补齐/对齐 `home.reminder_reorder` 及其 rect 作用域。
3. 明确区分 reorder 与 compact 的 rect 策略：
   - reorder：分区级 targeted rect
   - compact/count change：更大 list 区域 rect
4. List/Home toggle 语义以产品一致性优先，偏差必须文档化并可通过日志追溯。
5. 增强联动调试日志：
   - 触发源（home vs list）
   - pending-hide ids / hidden ids
   - reorder schedule/apply 时间点
   - 最终 reason + rects + R1/R2/R3 决策
6. 完成实机回归并把日志/截图回填到 issue。

## 实机回归场景
1. 在 List 连续 toggle reminder/inventory，验证 Home 同步稳定且可解释。
2. 在 Home toggle reminder/inventory，验证 delayed hide/reorder 行为与产品规则一致。
3. 等待 reorder/hide 到期，确认不存在“无原因消失”。
4. 在 pending reorder 期间快速切换 List <-> Home，确认无随机全刷。
5. 任一可见变化都能在日志中追溯到 reason 链路。

## 验收标准
- List/Home 联动符合 C++ 产品语义合同（含 reminder/inventory 统一进入 pending-hide 的覆盖规则）。
- C++ 路径中存在并实际命中 `home.reminder_reorder`。
- 正常交互下无无法解释的全刷。
- 用户可通过日志理解每次变化，不再“黑盒”。

## 非目标
- Timer/Memo/Calendar/Settings 对齐。
- 与 List/Home 联动无关的 UI 重设计与字体微调。
- 驱动波形策略实验。
