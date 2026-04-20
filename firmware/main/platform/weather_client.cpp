#include "platform/weather_client.hpp"

#include "esp_http_client.h"
#include "esp_log.h"

#include <cinttypes>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>

namespace fridge_ink::platform {

namespace {

static const char* kTag = "weather";

// ── HTTP response accumulator ────────────────────────────────────────────────

static std::string g_body;

static esp_err_t on_data(esp_http_client_event_t* evt) {
  if (evt->event_id == HTTP_EVENT_ON_DATA && evt->data_len > 0) {
    g_body.append(static_cast<const char*>(evt->data),
                  static_cast<std::size_t>(evt->data_len));
  }
  return ESP_OK;
}

// ── JSON helpers (manual — no library on ESP32) ───────────────────────────────

// Extract quoted string: "key":"<value>"  starting search at `from`.
// Returns empty on failure.
static std::string jstr(const std::string& body, const char* key,
                         std::size_t from = 0) {
  const std::string pat = std::string("\"") + key + "\":\"";
  const auto pos = body.find(pat, from);
  if (pos == std::string::npos) return {};
  const auto start = pos + pat.size();
  const auto end   = body.find('"', start);
  if (end == std::string::npos) return {};
  return body.substr(start, end - start);
}

// Extract integer from quoted value: "key":"<digits>"  (wttr.in wraps ints in quotes).
static int jint(const std::string& body, const char* key,
                std::size_t from = 0) {
  const std::string s = jstr(body, key, from);
  if (s.empty()) return 0;
  bool neg  = false;
  int  val  = 0;
  std::size_t i = 0;
  if (i < s.size() && s[i] == '-') { neg = true; ++i; }
  for (; i < s.size() && s[i] >= '0' && s[i] <= '9'; ++i)
    val = val * 10 + (s[i] - '0');
  return neg ? -val : val;
}

// Find position right after "key":[ (array open).
static std::size_t jarray_start(const std::string& body, const char* key,
                                  std::size_t from = 0) {
  const std::string pat = std::string("\"") + key + "\":[";
  const auto pos = body.find(pat, from);
  if (pos == std::string::npos) return std::string::npos;
  return pos + pat.size();
}

// ── Weather code mapping ──────────────────────────────────────────────────────
//
// draw_icon() does a case-insensitive substring search on the icon_key field:
//   "partly"             → partly-sunny icon
//   "sun" or "clear"     → sun icon
//   "rain" or "drizzle"  → rain icon
//   "snow"               → snow icon
//   "storm" or "thunder" → thunderstorm icon
//   "fog" or "haze"      → haze/fog icon
//   "hail"               → hail icon
//   (default)            → cloud icon
//
// We map wttr.in WMO-based codes to:
//   (human-readable label, icon_key containing the right substring)

struct CodeEntry {
  int  code;
  const char* label;
  const char* icon_key;
};

// clang-format off
static constexpr CodeEntry kCodeTable[] = {
  {113, "Sunny",               "sunny"},
  {116, "Partly Cloudy",       "partly_cloudy"},
  {119, "Cloudy",              "cloudy"},
  {122, "Overcast",            "cloudy"},
  {143, "Mist",                "fog"},
  {176, "Patchy Rain",         "rain"},
  {179, "Patchy Snow",         "snow"},
  {182, "Patchy Sleet",        "rain"},
  {185, "Patchy Freezing Drizzle", "drizzle"},
  {200, "Thunderstorm",        "thunderstorm"},
  {227, "Blowing Snow",        "snow"},
  {230, "Blizzard",            "snow"},
  {248, "Fog",                 "fog"},
  {260, "Freezing Fog",        "fog"},
  {263, "Light Drizzle",       "drizzle"},
  {266, "Drizzle",             "drizzle"},
  {281, "Freezing Drizzle",    "drizzle"},
  {284, "Heavy Freezing Drizzle", "drizzle"},
  {293, "Patchy Light Rain",   "rain"},
  {296, "Light Rain",          "rain"},
  {299, "Moderate Rain",       "rain"},
  {302, "Rain",                "rain"},
  {305, "Heavy Rain",          "rain"},
  {308, "Heavy Rain",          "rain"},
  {311, "Freezing Rain",       "rain"},
  {314, "Heavy Freezing Rain", "rain"},
  {317, "Sleet",               "rain"},
  {320, "Moderate Sleet",      "rain"},
  {323, "Light Snow",          "snow"},
  {326, "Light Snow",          "snow"},
  {329, "Moderate Snow",       "snow"},
  {332, "Snow",                "snow"},
  {335, "Heavy Snow",          "snow"},
  {338, "Heavy Snow",          "snow"},
  {350, "Ice Pellets",         "hail"},
  {353, "Rain Shower",         "rain"},
  {356, "Heavy Rain Shower",   "rain"},
  {359, "Torrential Rain",     "rain"},
  {362, "Sleet Shower",        "rain"},
  {365, "Heavy Sleet Shower",  "rain"},
  {368, "Snow Shower",         "snow"},
  {371, "Heavy Snow Shower",   "snow"},
  {374, "Ice Pellet Shower",   "hail"},
  {377, "Heavy Ice Pellets",   "hail"},
  {386, "Thundery Rain",       "thunderstorm"},
  {389, "Heavy Thundery Rain", "thunderstorm"},
  {392, "Thundery Snow",       "thunderstorm"},
  {395, "Heavy Thundery Snow", "thunderstorm"},
};
// clang-format on

static const CodeEntry* lookup_code(int code) {
  for (const auto& e : kCodeTable) {
    if (e.code == code) return &e;
  }
  return nullptr;
}

// ── Day-of-week helper ────────────────────────────────────────────────────────

static const char* kDow[7] = {"SUN","MON","TUE","WED","THU","FRI","SAT"};

static std::string day_name(int offset_days) {
  const std::time_t t  = std::time(nullptr);
  const struct tm*  tm = localtime(&t);
  return kDow[(tm->tm_wday + offset_days) % 7];
}

// ── Forecast day parser ───────────────────────────────────────────────────────
// Each day block in "weather":[ looks like:
//   { "date":"...", "maxtempC":"20", "mintempC":"10", "hourly":[...], ... }
// We find the Nth occurrence of "maxtempC" to locate day N.

static std::size_t find_nth(const std::string& body, const char* pat,
                             std::size_t from, int n) {
  std::size_t pos = from;
  for (int i = 0; i < n; ++i) {
    pos = body.find(pat, pos);
    if (pos == std::string::npos) return std::string::npos;
    if (i < n - 1) pos += std::strlen(pat);
  }
  return pos;
}

}  // namespace

// ── Public API ────────────────────────────────────────────────────────────────

WeatherResult weather_fetch(uint32_t timeout_ms) {
  WeatherResult result;
  g_body.clear();
  g_body.reserve(8192);  // wttr.in j1 responses are typically 6–8 KB

  esp_http_client_config_t cfg{};
  cfg.url           = "http://wttr.in?format=j1";
  cfg.event_handler = on_data;
  cfg.timeout_ms    = static_cast<int>(timeout_ms);

  auto* client = esp_http_client_init(&cfg);
  if (!client) {
    result.error = "http_init failed";
    ESP_LOGE(kTag, "%s", result.error.c_str());
    return result;
  }

  const esp_err_t err    = esp_http_client_perform(client);
  const int       status = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);

  if (err != ESP_OK) {
    result.error = std::string("http error: ") + esp_err_to_name(err);
    ESP_LOGW(kTag, "%s", result.error.c_str());
    return result;
  }
  if (status != 200) {
    result.error = std::string("http status ") + std::to_string(status);
    ESP_LOGW(kTag, "%s", result.error.c_str());
    return result;
  }

  ESP_LOGD(kTag, "Response %zu bytes", g_body.size());

  // ── Current conditions ────────────────────────────────────────────────────
  const int code = jint(g_body, "weatherCode");
  result.temperature_c    = jint(g_body, "temp_C");
  result.feels_like_c     = jint(g_body, "FeelsLikeC");
  result.humidity_percent = jint(g_body, "humidity");
  result.wind_kmh         = jint(g_body, "windspeedKmph");
  result.uv_index         = jint(g_body, "uvIndex");

  const auto* entry = lookup_code(code);
  result.condition = entry ? entry->label   : "Cloudy";
  result.icon_key  = entry ? entry->icon_key : "cloudy";

  // ── Location ─────────────────────────────────────────────────────────────
  result.location = jstr(g_body, "value");  // first "value" is areaName
  if (result.location.empty()) result.location = "Unknown";

  // ── Today hi/lo — first "maxtempC" / "mintempC" in weather[] ─────────────
  const std::size_t weather_arr = jarray_start(g_body, "weather");
  if (weather_arr != std::string::npos) {
    result.hi_c = jint(g_body, "maxtempC", weather_arr);
    result.lo_c = jint(g_body, "mintempC", weather_arr);
  }

  // ── 3-day forecast ────────────────────────────────────────────────────────
  for (int day = 0; day < 3; ++day) {
    // Find position of the Nth "maxtempC" in the body (1-indexed).
    const std::size_t pos =
        find_nth(g_body, "\"maxtempC\"", weather_arr == std::string::npos
                                             ? 0
                                             : weather_arr,
                 day + 1);
    if (pos == std::string::npos) break;

    auto& fd = result.forecast[static_cast<std::size_t>(day)];
    fd.dow  = day_name(day);
    fd.hi_c = jint(g_body, "maxtempC", pos);
    fd.lo_c = jint(g_body, "mintempC", pos);

    // Use first weatherCode in this day's hourly section for the icon.
    const std::size_t hourly_pos = jarray_start(g_body, "hourly", pos);
    const int day_code = hourly_pos != std::string::npos
                             ? jint(g_body, "weatherCode", hourly_pos)
                             : 0;
    const auto* de = lookup_code(day_code);
    fd.condition = de ? de->label   : "Cloudy";
    fd.icon_key  = de ? de->icon_key : "cloudy";
  }

  result.ok = true;
  ESP_LOGI(kTag, "OK: %s  %s  %d°C  humidity=%d%%  wind=%d km/h  UV=%d",
           result.location.c_str(), result.condition.c_str(),
           result.temperature_c, result.humidity_percent,
           result.wind_kmh, result.uv_index);
  return result;
}

}  // namespace fridge_ink::platform
