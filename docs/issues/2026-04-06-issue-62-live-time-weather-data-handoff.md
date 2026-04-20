# Issue #62 交接文档 — 时间/日期/天气真实数据对齐（产品级）

## 议题关系
- 总任务：#52（**OPEN**）
- 本文档目标：把“假数据/时间不准”单独收口，不和页面 UI 对齐工作混在一起。

## 产品问题（当前）
1. 天气/温度/湿度目前是静态默认值，不是真实数据。
2. 时间/日期存在“跑久了不准 or 本身不准”的用户感知问题。
3. timezone 配置未形成完整闭环，日期与本地时区一致性风险高。

## 现状证据（代码级）
- 固定天气默认值（非实时）：
  - `firmware/main/app/defaults.cpp`
  - `defaults.dashboard.weather_condition = "Rainy";`
  - `defaults.dashboard.weather_temperature_c = 17;`
  - `defaults.dashboard.weather_humidity_percent = 100;`
- 当前时间来源：
  - `firmware/main/platform/clock.cpp` 使用 `time(nullptr)`；
  - 仅支持串口手动 `t<epoch>` 写入时钟（`firmware/main/main.cpp`）。
- 兜底时间策略：
  - `firmware/main/app/defaults.cpp` 中 `kAllowBuildTimestampFallback = true`；
  - wall time 无效时会退到编译时间 minute bucket（不是实时真时钟）。
- timezone 现状：
  - `apply_posix_timezone()` 只在 defaults 路径调用；
  - onboarding/settings 中的 timezone 改动未形成系统级应用闭环。

## 目标（Definition of Done）
1. Home 的日期/时间来自真实时钟（可证明），不是编译时间假时钟。
2. Home 的天气/温度/湿度来自真实数据源（可证明），不是默认常量。
3. timezone 切换后，日期/星期/时钟显示按该时区一致。
4. 数据链路有可观测日志：来源、更新时间、失败原因、降级路径。

## 范围拆分（按顺序）

### A. 时间与日期链路（P0）
1. 建立“系统时钟同步”闭环：
   - 启动后自动同步（网络可用时）；
   - 周期性重同步（例如每 6 小时）；
   - 保留手动 `t<epoch>` 作为 debug 入口。
2. 显式区分时间状态：
   - `real_synced` / `fallback_unsynced`；
   - 在日志和 state 中可见，避免“看起来像真时间但其实是编译时间”。
3. timezone 应用闭环：
   - settings/onboarding timezone 变化后，应用到系统 TZ；
   - calendar/home 日期和 weekday 与 timezone 一致。

### B. 天气/温湿度真实数据链路（P0）
1. 明确数据源（与 Python 行为一致）：
   - 参考 Python `app/data/weather_api.py`（Open-Meteo）。
2. 建立 C++ 侧拉取与更新机制：
   - 获取 location -> forecast（含温度、湿度、天气 condition）；
   - 成功后写入 `dashboard.weather_*`；
   - 失败时保留最近一次成功值，不回退到硬编码常量。
3. 增加新鲜度与失败可见性：
   - `last_weather_sync_ms` / `weather_sync_state`；
   - 日志记录请求成功/失败原因、数据时间戳。

### C. 刷新策略与渲染联动（P1）
1. 数据更新触发 `home.weather_update` dirty reason。
2. 只刷新天气区域（partial 优先），避免无关全刷。
3. 日志包含：weather dirty reason、rect、R1/R2/R3 决策。

## 非目标
- 不在本 Issue 做 Home 静态排版重设计。
- 不改 `third_party/waveshare_ePaper`。
- 不混入 calendar/settings/timer/memo 的视觉对齐任务。

## 验收标准（实机）
1. 网络可用场景：
   - 开机后可在限定时间内拿到真实时间与天气数据；
   - Home 显示值与外部来源一致（允许小范围延迟）。
2. 网络不可用场景：
   - 明确标识 `unsynced/fallback`；
   - 不出现“伪实时”误导（例如继续显示编译时间却无状态提示）。
3. timezone 场景：
   - 切换 timezone 后，日期/星期/时间与目标时区一致。
4. 长时运行场景（至少 2 小时）：
   - 无明显时钟跳变/倒退；
   - 数据刷新日志完整可追溯。

## 建议实现文件（C++）
- `firmware/main/platform/clock.cpp`（时钟状态与同步接口）
- `firmware/main/app/defaults.cpp`（去除“伪实时”兜底策略的误用）
- `firmware/main/app/reducer.cpp`（timezone 变更应用）
- `firmware/main/app/runtime.cpp`（数据更新与 refresh 决策日志）
- `firmware/main/app/state.hpp`（sync 状态字段）
- （新增）weather/time service 模块（建议独立文件，避免污染 reducer）

## 参考 Python（行为基线）
- `app/data/weather_api.py`
- `app/data/mock.py`（当前 Python 的 live+fallback 结构）
- `app/render/refresh_policy.py`（`home.weather_update`）
