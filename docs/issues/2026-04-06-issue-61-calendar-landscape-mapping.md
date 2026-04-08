# Issue #61 Calendar 横屏 Python→C++ 对照表（函数级）

## 1) Reducer 语义映射

| Python 基线 | C++ 现状（改动前） | 差异 |
|---|---|---|
| `app/core/reducer.py::_open_calendar_from_home`：进入 Calendar 时重置 `calendar_offset_days=0/calendar_mode=date/calendar_selected_index=0` | `firmware/main/app/reducer.cpp::open_menu_target` 与 Home click 仅 `state.screen=Screen::Calendar` | 缺少状态重置 |
| `app/core/reducer.py::Rotate@Screen.CALENDAR`：`date` 模式改 offset；`agenda` 模式改 selected index（按 agenda 长度 clamp） | `firmware/main/app/reducer.cpp::handle_rotate` 无 `Screen::Calendar` 分支 | 缺失（P0） |
| `app/core/reducer.py::Click@Screen.CALENDAR`：`date->agenda`；`agenda` 下仅 reminder 可 toggle；无可 toggle 则回退 `date` | `firmware/main/app/reducer.cpp::handle_click` 对 Calendar 落入“detail do nothing” | 缺失（P0） |
| `app/core/reducer.py::LongPress/Back`：非 Home 返回 Home | `firmware/main/app/reducer.cpp::handle_long_press/handle_back` 已满足 | 一致 |

## 2) UI 渲染结构映射（横屏）

| Python 基线 | C++ 现状（改动前） | 差异 |
|---|---|---|
| `app/ui/calendar.py`：左月历网格 + 右当天 agenda（事件在前，reminder 在后） | `firmware/main/ui/screens/calendar_screen_landscape.cpp`：左月历 + 右静态 agenda 卡片 | agenda 数据源不一致（静态占位） |
| Python 横屏 header：右侧 `weekday + date_title`，无固定占位 chip | C++ 右侧 `AGENDA + weekday + month_line + DAY chip` | 视觉层级与文案不一致 |
| Python 空态：`NO EVENTS` + `Voice can add reminders and memos` | C++ 无对应空态分支（总是渲染 3 张静态卡） | 空态不一致 |
| Python footer：按 `calendar_mode` 切换 `Rotate=Date/Item` + `Click=Agenda/Toggle` | C++ footer 固定 `ROTATE=DATE | CLICK=AGENDA | HOLD=HOME` | 模式提示不一致 |

## 3) Refresh（dirty reasons/rect）映射

| Python 基线 | C++ 现状（改动前） | 差异 |
|---|---|---|
| `app/render/refresh_policy.py::infer_dirty_rects_with_reasons@Calendar`：`calendar.date_or_mode_or_data` / `calendar.agenda_focus_move` + `left_grid/right_header/right_agenda` 细分 | C++ runtime 仅 Home/Timer 有显式 dirty 规划，其余主要依赖 `diff_only` | Calendar dirty reason/rect 缺失 |
| Python 在切入 Calendar 时可给 `left_panel + right_panel` | C++ 屏切换靠 diff + screen.change reason | 可解释性不足 |

## 4) 结论（改动目标）

1. reducer 增加 Calendar rotate/click 完整语义，并在进入 Calendar 时 reset 状态。  
2. landscape renderer 移除静态 `kAgendaItems`，改为 state/model 驱动。  
3. runtime 增加 Calendar dirty 推导与 reason，匹配 Python 的语义命名与区域拆分。  
