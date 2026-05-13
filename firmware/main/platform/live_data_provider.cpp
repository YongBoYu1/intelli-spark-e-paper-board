#include "platform/live_data_provider.hpp"

#include "platform/clock.hpp"
#include "platform/wifi_driver.hpp"

#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag = "live_data";
// Fallback poll interval used when wall time is unavailable or when inside a
// sync window (00:xx / 12:xx) so we keep retrying on transient failures.
constexpr uint32_t kTaskPollDelayMs = 5000U;
// How many seconds before 00:00 / 12:00 to wake up and start polling.
constexpr uint32_t kSyncWindowLeadS = 30U;
constexpr uint32_t kHttpTimeoutMs = 8000U;
// Fallback: if wall clock is unavailable (NTP failed), sync every 12 h by
// elapsed monotonic time so scheduled updates still happen.
constexpr uint64_t kElapsedSyncIntervalMs = 12ULL * 60 * 60 * 1000;

struct HttpResult {
  bool ok{false};
  int status{-1};
  std::string body{};
  std::string error{};
};

struct ResolvedLocation {
  bool ok{false};
  std::string source{};
  std::string label{};
  std::string timezone{};
  double latitude{0.0};
  double longitude{0.0};
  std::string error{};
};

struct WeatherFetchResult {
  bool ok{false};
  std::string source{};
  std::string location{};
  std::string condition{};
  std::string icon{"cloud"};
  int temperature_c{0};
  int humidity_percent{0};
  int feels_like_c{0};
  int hi_c{0};
  int lo_c{0};
  int wind_kmh{0};
  int uv_index{0};
  std::array<WeatherForecastDaySample, 3> forecast_days{};
  std::time_t observed_unix_seconds{0};
  std::string error{};
};

struct ProviderState {
  bool bootstrapped{false};
  bool task_started{false};
  bool force_sync{false};
  bool sample_pending{false};
  bool has_success{false};
  bool sync_in_progress{false};
  std::uint64_t last_attempt_ms{0};
  std::uint64_t last_success_ms{0};
  std::int64_t last_auto_sync_slot_id{-1};
  std::string timezone_name{};
  std::string location_hint{};
  WeatherFetchResult latest{};
};

static ProviderState g_state{};
static SemaphoreHandle_t g_mutex{nullptr};

static std::string g_http_body{};

SemaphoreHandle_t provider_mutex() {
  if (g_mutex == nullptr) {
    g_mutex = xSemaphoreCreateMutex();
  }
  return g_mutex;
}

bool lock_provider(const TickType_t wait_ticks = portMAX_DELAY) {
  SemaphoreHandle_t mutex = provider_mutex();
  return mutex != nullptr && xSemaphoreTake(mutex, wait_ticks) == pdTRUE;
}

void unlock_provider() {
  if (g_mutex != nullptr) {
    xSemaphoreGive(g_mutex);
  }
}

std::string trim_copy(const char* value) {
  std::string out = value != nullptr ? value : "";
  const auto first = out.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return {};
  }
  const auto last = out.find_last_not_of(" \t\r\n");
  return out.substr(first, last - first + 1U);
}

esp_err_t on_http_event(esp_http_client_event_t* evt) {
  if (evt == nullptr) {
    return ESP_OK;
  }
  if (evt->event_id == HTTP_EVENT_ON_DATA &&
      evt->data != nullptr &&
      evt->data_len > 0) {
    g_http_body.append(
        static_cast<const char*>(evt->data),
        static_cast<std::size_t>(evt->data_len));
  }
  return ESP_OK;
}

HttpResult http_get_text(const std::string& url, const uint32_t timeout_ms) {
  HttpResult result{};
  g_http_body.clear();
  g_http_body.reserve(1024);

  esp_http_client_config_t cfg{};
  cfg.url = url.c_str();
  cfg.method = HTTP_METHOD_GET;
  cfg.timeout_ms = static_cast<int>(timeout_ms);
  cfg.buffer_size = 512;
  cfg.buffer_size_tx = 512;
  cfg.event_handler = on_http_event;

  esp_http_client_handle_t client = esp_http_client_init(&cfg);
  if (client == nullptr) {
    result.error = "esp_http_client_init_failed";
    return result;
  }

  const esp_err_t err = esp_http_client_perform(client);
  result.status = esp_http_client_get_status_code(client);
  result.body = g_http_body;
  esp_http_client_cleanup(client);

  if (err != ESP_OK) {
    result.error = esp_err_to_name(err);
    return result;
  }
  if (result.status != 200) {
    char status_buf[32];
    snprintf(status_buf, sizeof(status_buf), "http_%d", result.status);
    result.error = status_buf;
    return result;
  }
  result.ok = true;
  return result;
}

std::string json_extract_string(const std::string& body, const char* key) {
  const std::string needle = std::string("\"") + key + "\":\"";
  const std::size_t pos = body.find(needle);
  if (pos == std::string::npos) {
    return {};
  }
  const std::size_t start = pos + needle.size();
  std::size_t end = start;
  while (end < body.size()) {
    if (body[end] == '"' && body[end - 1] != '\\') {
      break;
    }
    ++end;
  }
  if (end <= start || end >= body.size()) {
    return {};
  }
  return body.substr(start, end - start);
}

double json_extract_number(const std::string& body, const char* key, bool* ok_out = nullptr) {
  const std::string needle = std::string("\"") + key + "\":";
  const std::size_t pos = body.find(needle);
  if (pos == std::string::npos) {
    if (ok_out != nullptr) {
      *ok_out = false;
    }
    return 0.0;
  }
  std::size_t start = pos + needle.size();
  while (start < body.size() &&
         (body[start] == ' ' || body[start] == '\n' || body[start] == '\r' || body[start] == '\t')) {
    ++start;
  }
  std::size_t end = start;
  if (end < body.size() && (body[end] == '-' || body[end] == '+')) {
    ++end;
  }
  while (end < body.size() &&
         ((body[end] >= '0' && body[end] <= '9') || body[end] == '.')) {
    ++end;
  }
  if (end <= start) {
    if (ok_out != nullptr) {
      *ok_out = false;
    }
    return 0.0;
  }
  const std::string token = body.substr(start, end - start);
  char* parse_end = nullptr;
  const double parsed = std::strtod(token.c_str(), &parse_end);
  const bool ok = parse_end != nullptr && *parse_end == '\0';
  if (ok_out != nullptr) {
    *ok_out = ok;
  }
  return ok ? parsed : 0.0;
}

std::string json_extract_array_body(const std::string& body, const char* key) {
  const std::string needle = std::string("\"") + key + "\":[";
  const std::size_t pos = body.find(needle);
  if (pos == std::string::npos) {
    return {};
  }
  std::size_t i = pos + needle.size();
  int depth = 1;
  bool in_string = false;
  for (; i < body.size(); ++i) {
    const char ch = body[i];
    if (in_string) {
      if (ch == '"' && (i == 0 || body[i - 1] != '\\')) {
        in_string = false;
      }
      continue;
    }
    if (ch == '"') {
      in_string = true;
      continue;
    }
    if (ch == '[') {
      ++depth;
    } else if (ch == ']') {
      --depth;
      if (depth == 0) {
        return body.substr(pos + needle.size(), i - (pos + needle.size()));
      }
    }
  }
  return {};
}

std::vector<double> json_parse_number_array(const std::string& body) {
  std::vector<double> values{};
  std::size_t i = 0;
  while (i < body.size()) {
    while (i < body.size() &&
           (body[i] == ' ' || body[i] == '\n' || body[i] == '\r' || body[i] == '\t' || body[i] == ',')) {
      ++i;
    }
    if (i >= body.size()) {
      break;
    }
    std::size_t start = i;
    if (body[i] == '-' || body[i] == '+') {
      ++i;
    }
    while (i < body.size() &&
           ((body[i] >= '0' && body[i] <= '9') || body[i] == '.')) {
      ++i;
    }
    if (i <= start) {
      break;
    }
    char* end = nullptr;
    const std::string token = body.substr(start, i - start);
    const double value = std::strtod(token.c_str(), &end);
    if (end != nullptr && *end == '\0') {
      values.push_back(value);
    }
  }
  return values;
}

std::vector<std::string> json_parse_string_array(const std::string& body) {
  std::vector<std::string> values{};
  std::size_t i = 0;
  while (i < body.size()) {
    while (i < body.size() && body[i] != '"') {
      ++i;
    }
    if (i >= body.size()) {
      break;
    }
    ++i;
    std::size_t start = i;
    while (i < body.size()) {
      if (body[i] == '"' && body[i - 1] != '\\') {
        break;
      }
      ++i;
    }
    if (i <= start || i >= body.size()) {
      break;
    }
    values.push_back(body.substr(start, i - start));
    ++i;
  }
  return values;
}

int rounded_or_default(const double value, const int fallback = 0) {
  if (!std::isfinite(value)) {
    return fallback;
  }
  return static_cast<int>(std::lround(value));
}

std::string weekday_upper_from_iso_date(const std::string& iso_date) {
  int year = 0;
  int month = 0;
  int day = 0;
  if (std::sscanf(iso_date.c_str(), "%d-%d-%d", &year, &month, &day) != 3) {
    return "--";
  }
  std::tm tm{};
  tm.tm_year = year - 1900;
  tm.tm_mon = month - 1;
  tm.tm_mday = day;
  tm.tm_isdst = -1;
  if (std::mktime(&tm) < 0) {
    return "--";
  }
  static constexpr std::array<const char*, 7> kDays = {
      "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
  const int idx = std::max(0, std::min(6, tm.tm_wday));
  return kDays[static_cast<std::size_t>(idx)];
}

std::string url_encode(const std::string& text) {
  static constexpr char kHex[] = "0123456789ABCDEF";
  std::string out;
  out.reserve(text.size() * 3U);
  for (const unsigned char ch : text) {
    if ((ch >= 'a' && ch <= 'z') ||
        (ch >= 'A' && ch <= 'Z') ||
        (ch >= '0' && ch <= '9') ||
        ch == '-' || ch == '_' || ch == '.' || ch == '~') {
      out.push_back(static_cast<char>(ch));
    } else if (ch == ' ') {
      out.push_back('+');
    } else {
      out.push_back('%');
      out.push_back(kHex[(ch >> 4) & 0x0F]);
      out.push_back(kHex[ch & 0x0F]);
    }
  }
  return out;
}

std::string weather_condition_from_wmo(const int code) {
  if (code == 0) {
    return "Sunny";
  }
  if (code == 1) {
    return "Clear";
  }
  if (code == 2) {
    return "Partly Cloudy";
  }
  if (code == 3) {
    return "Cloudy";
  }
  if (code == 45 || code == 48) {
    return "Haze";
  }
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
    return "Rainy";
  }
  if ((code >= 71 && code <= 77) || code == 85 || code == 86) {
    return "Snow";
  }
  if (code == 95 || code == 96 || code == 99) {
    return "Storm";
  }
  return "Cloudy";
}

std::string weather_icon_from_wmo(const int code) {
  if (code == 0) {
    return "sun";
  }
  if (code == 1) {
    return "clear";
  }
  if (code == 2) {
    return "partly_cloudy";
  }
  if (code == 3) {
    return "cloud";
  }
  if (code == 45 || code == 48) {
    return "haze";
  }
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
    return "rain";
  }
  if ((code >= 71 && code <= 77) || code == 85 || code == 86) {
    return "snow";
  }
  if (code == 95 || code == 96 || code == 99) {
    return "storm";
  }
  return "cloud";
}

ResolvedLocation resolve_location_from_ip() {
  ResolvedLocation out{};
  if (!wifi_is_connected()) {
    out.error = "wifi_disconnected";
    return out;
  }

  const HttpResult http = http_get_text(
      "http://ip-api.com/json?fields=status,city,lat,lon,timezone",
      kHttpTimeoutMs);
  if (!http.ok) {
    out.error = http.error.empty() ? "ip_geo_failed" : http.error;
    return out;
  }
  if (json_extract_string(http.body, "status") != "success") {
    out.error = "ip_geo_unsuccessful";
    return out;
  }

  bool lat_ok = false;
  bool lon_ok = false;
  const double latitude = json_extract_number(http.body, "lat", &lat_ok);
  const double longitude = json_extract_number(http.body, "lon", &lon_ok);
  if (!lat_ok || !lon_ok) {
    out.error = "ip_geo_missing_lat_lon";
    return out;
  }

  out.ok = true;
  out.source = "wifi_ip_geo";
  out.label = json_extract_string(http.body, "city");
  out.timezone = json_extract_string(http.body, "timezone");
  out.latitude = latitude;
  out.longitude = longitude;
  return out;
}

ResolvedLocation resolve_location_from_hint(const std::string& hint) {
  ResolvedLocation out{};
  if (hint.empty()) {
    out.error = "missing_location_hint";
    return out;
  }

  const std::string url =
      "http://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json&name=" +
      url_encode(hint);
  const HttpResult http = http_get_text(url, kHttpTimeoutMs);
  if (!http.ok) {
    out.error = http.error.empty() ? "hint_geocode_failed" : http.error;
    return out;
  }
  if (http.body.find("\"results\"") == std::string::npos) {
    out.error = "hint_geocode_no_results";
    return out;
  }

  bool lat_ok = false;
  bool lon_ok = false;
  const double latitude = json_extract_number(http.body, "latitude", &lat_ok);
  const double longitude = json_extract_number(http.body, "longitude", &lon_ok);
  if (!lat_ok || !lon_ok) {
    out.error = "hint_geocode_missing_lat_lon";
    return out;
  }

  out.ok = true;
  out.source = "location_hint";
  out.label = json_extract_string(http.body, "name");
  out.timezone = json_extract_string(http.body, "timezone");
  out.latitude = latitude;
  out.longitude = longitude;
  return out;
}

ResolvedLocation resolve_location(const std::string& location_hint) {
  ResolvedLocation location = resolve_location_from_ip();
  if (location.ok) {
    return location;
  }

  const std::string ip_error = location.error;
  location = resolve_location_from_hint(location_hint);
  if (location.ok) {
    if (!ip_error.empty()) {
      ESP_LOGW(
          kTag,
          "WiFi IP geolocation unavailable (%s), using location hint \"%s\"",
          ip_error.c_str(),
          location.label.c_str());
    }
    return location;
  }

  if (location.error.empty()) {
    location.error = ip_error.empty() ? "location_unresolved" : ip_error;
  } else if (!ip_error.empty()) {
    location.error += ";";
    location.error += ip_error;
  }
  return location;
}

WeatherFetchResult fetch_weather_sample(
    const std::string& timezone_name,
    const std::string& location_hint) {
  WeatherFetchResult out{};
  const ResolvedLocation location = resolve_location(location_hint);
  if (!location.ok) {
    out.error = location.error.empty() ? "location_unresolved" : location.error;
    return out;
  }

  char lat_buf[32];
  char lon_buf[32];
  snprintf(lat_buf, sizeof(lat_buf), "%.5f", location.latitude);
  snprintf(lon_buf, sizeof(lon_buf), "%.5f", location.longitude);

  const std::string tz = !location.timezone.empty()
                             ? location.timezone
                             : (!timezone_name.empty() ? timezone_name : "auto");
  const std::string url =
      "http://api.open-meteo.com/v1/forecast?latitude=" + std::string(lat_buf) +
      "&longitude=" + std::string(lon_buf) +
      "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,uv_index"
      "&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,wind_speed_10m_max,uv_index_max,relative_humidity_2m_max"
      "&forecast_days=4&timezone=" + url_encode(tz.empty() ? "auto" : tz);

  const HttpResult http = http_get_text(url, kHttpTimeoutMs);
  if (!http.ok) {
    out.error = http.error.empty() ? "weather_fetch_failed" : http.error;
    return out;
  }

  const std::size_t current_pos = http.body.find("\"current\":{");
  if (current_pos == std::string::npos) {
    out.error = "weather_missing_current";
    return out;
  }
  const std::string current_body = http.body.substr(current_pos);

  bool temp_ok = false;
  bool humidity_ok = false;
  bool code_ok = false;
  bool feels_ok = false;
  bool wind_ok = false;
  bool uv_ok = false;
  const double temp = json_extract_number(current_body, "temperature_2m", &temp_ok);
  const double humidity = json_extract_number(current_body, "relative_humidity_2m", &humidity_ok);
  const double feels_like = json_extract_number(current_body, "apparent_temperature", &feels_ok);
  const double weather_code = json_extract_number(current_body, "weather_code", &code_ok);
  const double wind_kmh = json_extract_number(current_body, "wind_speed_10m", &wind_ok);
  const double uv_index = json_extract_number(current_body, "uv_index", &uv_ok);
  if (!temp_ok || !humidity_ok || !code_ok) {
    out.error = "weather_missing_fields";
    return out;
  }

  const std::size_t daily_pos = http.body.find("\"daily\":{");
  if (daily_pos == std::string::npos) {
    out.error = "weather_missing_daily";
    return out;
  }
  const std::string daily_body = http.body.substr(daily_pos);
  const std::vector<std::string> daily_times =
      json_parse_string_array(json_extract_array_body(daily_body, "time"));
  const std::vector<double> daily_weather_codes =
      json_parse_number_array(json_extract_array_body(daily_body, "weather_code"));
  const std::vector<double> daily_hi =
      json_parse_number_array(json_extract_array_body(daily_body, "temperature_2m_max"));
  const std::vector<double> daily_lo =
      json_parse_number_array(json_extract_array_body(daily_body, "temperature_2m_min"));
  const std::vector<double> daily_feels =
      json_parse_number_array(json_extract_array_body(daily_body, "apparent_temperature_max"));
  const std::vector<double> daily_wind =
      json_parse_number_array(json_extract_array_body(daily_body, "wind_speed_10m_max"));
  const std::vector<double> daily_uv =
      json_parse_number_array(json_extract_array_body(daily_body, "uv_index_max"));

  const std::size_t daily_count = std::min(
      std::min(daily_times.size(), daily_weather_codes.size()),
      std::min(daily_hi.size(), daily_lo.size()));
  if (daily_count == 0) {
    out.error = "weather_empty_daily";
    return out;
  }

  out.ok = true;
  out.source = location.source + "+open_meteo";
  out.location = location.label.empty() ? location_hint : location.label;
  out.temperature_c = rounded_or_default(temp);
  out.humidity_percent = rounded_or_default(humidity);
  out.feels_like_c = feels_ok ? rounded_or_default(feels_like) : rounded_or_default(temp);
  out.hi_c = rounded_or_default(daily_hi[0], out.temperature_c);
  out.lo_c = rounded_or_default(daily_lo[0], out.temperature_c);
  out.wind_kmh = wind_ok ? rounded_or_default(wind_kmh) :
                 (!daily_wind.empty() ? rounded_or_default(daily_wind[0]) : 0);
  out.uv_index = uv_ok ? rounded_or_default(uv_index) :
                 (!daily_uv.empty() ? rounded_or_default(daily_uv[0]) : 0);
  out.condition = weather_condition_from_wmo(rounded_or_default(weather_code));
  out.icon = weather_icon_from_wmo(rounded_or_default(weather_code));
  for (std::size_t i = 1; i < daily_count && i <= out.forecast_days.size(); ++i) {
    WeatherForecastDaySample& day = out.forecast_days[i - 1];
    day.dow = weekday_upper_from_iso_date(daily_times[i]);
    day.condition = weather_condition_from_wmo(rounded_or_default(daily_weather_codes[i]));
    day.icon = weather_icon_from_wmo(rounded_or_default(daily_weather_codes[i]));
    day.hi_c = rounded_or_default(daily_hi[i]);
    day.lo_c = rounded_or_default(daily_lo[i]);
  }
  out.observed_unix_seconds = std::time(nullptr);
  return out;
}

std::int64_t current_auto_sync_slot_id() {
  if (!wall_time_is_valid()) {
    return -1;
  }
  const std::time_t now = wall_time_seconds();
  std::tm local_tm{};
  if (localtime_r(&now, &local_tm) == nullptr) {
    return -1;
  }
  if (local_tm.tm_hour != 0 && local_tm.tm_hour != 12) {
    return -1;
  }
  return (static_cast<std::int64_t>(local_tm.tm_year + 1900) * 1000000LL) +
         (static_cast<std::int64_t>(local_tm.tm_yday + 1) * 10LL) +
         (local_tm.tm_hour == 12 ? 1LL : 0LL);
}

// Return how long the weather task should sleep before its next poll.
//
// Outside both sync windows:  sleep until kSyncWindowLeadS seconds before the
//   next 00:00 or 12:00 (up to ~6 hours).  This eliminates thousands of
//   pointless 5-second wakeups every day.
// Inside a sync window (h==0 or h==12):  return kTaskPollDelayMs so the task
//   keeps retrying quickly until the fetch succeeds.
// No valid wall time:  sleep up to kElapsedSyncIntervalMs from last success
//   so the elapsed-time fallback fires on schedule without busy-spinning.
static TickType_t smart_sleep_ticks() {
  if (!wall_time_is_valid()) {
    // Wall clock unavailable (NTP failed).  Sleep until the elapsed-sync
    // interval would fire, capped at 6 h so we don't miss it by much.
    if (g_state.has_success && g_state.last_success_ms > 0) {
      const uint64_t elapsed_ms = monotonic_ms() - g_state.last_success_ms;
      if (elapsed_ms < kElapsedSyncIntervalMs) {
        const uint64_t remain_ms = kElapsedSyncIntervalMs - elapsed_ms;
        const uint32_t capped_ms = static_cast<uint32_t>(
            std::min(remain_ms, static_cast<uint64_t>(6ULL * 3600 * 1000)));
        return pdMS_TO_TICKS(capped_ms);
      }
    }
    return pdMS_TO_TICKS(kTaskPollDelayMs);
  }
  const std::time_t now = wall_time_seconds();
  std::tm local_tm{};
  if (localtime_r(&now, &local_tm) == nullptr) {
    return pdMS_TO_TICKS(kTaskPollDelayMs);
  }
  const int h = local_tm.tm_hour;
  // Inside a sync window — keep polling every 5 s for retry logic.
  if (h == 0 || h == 12) {
    return pdMS_TO_TICKS(kTaskPollDelayMs);
  }
  // Seconds elapsed since midnight.
  const int day_s = h * 3600 + local_tm.tm_min * 60 + local_tm.tm_sec;
  // Next sync window: 12:00 or tomorrow's 00:00.
  const int next_s = (h < 12) ? (12 * 3600) : (24 * 3600);
  const int sleep_s = next_s - day_s - static_cast<int>(kSyncWindowLeadS);
  if (sleep_s <= 0) {
    // We're within the lead-up window — poll normally.
    return pdMS_TO_TICKS(kTaskPollDelayMs);
  }
  // Cap at 6 hours to tolerate NTP drift / DST changes gracefully.
  const uint32_t capped_s = static_cast<uint32_t>(std::min(sleep_s, 6 * 3600));
  return pdMS_TO_TICKS(capped_s * 1000U);
}

void weather_sync_task(void* /*arg*/) {
  while (true) {
    bool should_sync  = false;
    bool is_auto_sync = false;
    std::int64_t auto_slot_id = -1;  // kept for post-sync slot recording
    std::string timezone_name{};
    std::string location_hint{};

    if (lock_provider(pdMS_TO_TICKS(100))) {
      const std::uint64_t now_ms = monotonic_ms();
      const std::int64_t slot_id = current_auto_sync_slot_id();

      // Retry initial sync on every poll until the first success — the old
      // `last_attempt_ms == 0` guard was preventing retries after the first
      // failed boot attempt.
      const bool initial_sync = !g_state.has_success;

      is_auto_sync = slot_id >= 0 && slot_id != g_state.last_auto_sync_slot_id;

      // Fallback: if NTP never synced (wall_time_is_valid() == false), the
      // slot_id is always -1 and is_auto_sync is always false.  Use elapsed
      // monotonic time so the 12-hourly update still fires even without a
      // valid wall clock.
      const bool elapsed_sync = g_state.has_success &&
          (now_ms - g_state.last_success_ms >= kElapsedSyncIntervalMs);

      should_sync  = g_state.bootstrapped &&
                     (g_state.force_sync || initial_sync || is_auto_sync || elapsed_sync);

      if (should_sync) {
        timezone_name = g_state.timezone_name;
        location_hint = g_state.location_hint;
        g_state.last_attempt_ms = now_ms;
        g_state.sync_in_progress = true;
        if (g_state.force_sync) {
          g_state.force_sync = false;
          is_auto_sync = false;
        } else if (is_auto_sync) {
          // Save slot_id but do NOT record it as consumed yet.
          // We only mark the slot done after a successful fetch so that
          // a transient WiFi outage during the 00:xx / 12:xx window
          // does not silently skip the whole scheduled update.
          auto_slot_id = slot_id;
        }
      }
      unlock_provider();
    }

    if (!should_sync) {
      vTaskDelay(smart_sleep_ticks());
      continue;
    }

    WeatherFetchResult result = fetch_weather_sample(timezone_name, location_hint);

    if (lock_provider()) {
      if (!result.ok && g_state.has_success) {
        // Carry forward the last good reading so the UI stays populated.
        result.location              = g_state.latest.location;
        result.condition             = g_state.latest.condition;
        result.icon                  = g_state.latest.icon;
        result.temperature_c         = g_state.latest.temperature_c;
        result.humidity_percent      = g_state.latest.humidity_percent;
        result.feels_like_c          = g_state.latest.feels_like_c;
        result.hi_c                  = g_state.latest.hi_c;
        result.lo_c                  = g_state.latest.lo_c;
        result.wind_kmh              = g_state.latest.wind_kmh;
        result.uv_index              = g_state.latest.uv_index;
        result.forecast_days         = g_state.latest.forecast_days;
        result.observed_unix_seconds = g_state.latest.observed_unix_seconds;
      }
      if (result.ok) {
        g_state.has_success      = true;
        g_state.last_success_ms  = monotonic_ms();
        // Cache the resolved city so future syncs can use it as a geocoding
        // fallback when IP-geolocation is unavailable (e.g. WiFi still
        // connects but ip-api.com is slow, or the location_hint was empty).
        if (!result.location.empty()) {
          g_state.location_hint = result.location;
        }
        // Mark the scheduled slot as consumed only on success.
        // Failed attempts leave the slot open so the task retries every
        // kTaskPollDelayMs until WiFi recovers within the same hour window.
        if (auto_slot_id >= 0) {
          g_state.last_auto_sync_slot_id = auto_slot_id;
        }
      }
      g_state.latest         = result;
      g_state.sample_pending = true;
      g_state.sync_in_progress = false;
      unlock_provider();
    }

    if (result.ok) {
      ESP_LOGI(
          kTag,
          "Weather sync ok source=%s location=%s temp=%dC humidity=%d%% condition=%s",
          result.source.c_str(),
          result.location.c_str(),
          result.temperature_c,
          result.humidity_percent,
          result.condition.c_str());
    } else {
      ESP_LOGW(
          kTag,
          "Weather sync failed mode=%s: %s",
          is_auto_sync ? "scheduled" : "manual_or_boot",
          result.error.c_str());
    }
  }
}

void ensure_task_started() {
  if (lock_provider()) {
    const bool should_start = !g_state.task_started;
    if (should_start) {
      g_state.task_started = true;
    }
    unlock_provider();
    if (should_start) {
      xTaskCreate(weather_sync_task, "weather_sync", 8192, nullptr, 4, nullptr);
    }
  }
}

}  // namespace

bool live_data_bootstrap(const char* timezone_name, const char* location_hint) {
  if (!lock_provider()) {
    return false;
  }
  g_state.bootstrapped = true;
  g_state.force_sync = true;
  g_state.timezone_name = trim_copy(timezone_name);
  g_state.location_hint = trim_copy(location_hint);
  unlock_provider();
  ensure_task_started();
  return true;
}

bool live_data_request_sync_now() {
  if (!lock_provider()) {
    return false;
  }
  const bool bootstrapped = g_state.bootstrapped;
  if (bootstrapped) {
    g_state.force_sync = true;
  }
  unlock_provider();
  if (bootstrapped) {
    ensure_task_started();
  }
  return bootstrapped;
}

bool live_data_weather_sync_in_progress() {
  if (!lock_provider(pdMS_TO_TICKS(10))) {
    return false;
  }
  const bool in_progress = g_state.sync_in_progress;
  unlock_provider();
  return in_progress;
}

bool live_data_poll_clock(ClockSyncSample* sample_out) {
  (void)sample_out;
  return false;
}

bool live_data_poll_weather(WeatherSyncSample* sample_out) {
  if (sample_out == nullptr) {
    return false;
  }
  if (!lock_provider(pdMS_TO_TICKS(10))) {
    return false;
  }
  if (!g_state.sample_pending) {
    unlock_provider();
    return false;
  }

  g_state.sample_pending = false;
  sample_out->valid = true;
  sample_out->synced = g_state.latest.ok;
  sample_out->location = g_state.latest.location;
  sample_out->condition = g_state.latest.condition;
  sample_out->icon = g_state.latest.icon;
  sample_out->temperature_c = g_state.latest.temperature_c;
  sample_out->humidity_percent = g_state.latest.humidity_percent;
  sample_out->feels_like_c = g_state.latest.feels_like_c;
  sample_out->hi_c = g_state.latest.hi_c;
  sample_out->lo_c = g_state.latest.lo_c;
  sample_out->wind_kmh = g_state.latest.wind_kmh;
  sample_out->uv_index = g_state.latest.uv_index;
  sample_out->forecast_days = g_state.latest.forecast_days;
  sample_out->observed_unix_seconds = g_state.latest.observed_unix_seconds;
  sample_out->source = g_state.latest.source;
  sample_out->error = g_state.latest.error;
  unlock_provider();
  return true;
}

}  // namespace fridge_ink::platform
