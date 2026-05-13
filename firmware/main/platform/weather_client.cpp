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
// Handles both compact JSON ("key":"val") and pretty-printed ("key": "val").
static std::string jstr(const std::string& body, const char* key,
                         std::size_t from = 0) {
  const std::string pat = std::string("\"") + key + "\":";
  auto pos = body.find(pat, from);
  if (pos == std::string::npos) return {};
  pos += pat.size();
  // skip optional whitespace between ':' and the opening '"'
  while (pos < body.size() &&
         (body[pos] == ' ' || body[pos] == '\t' ||
          body[pos] == '\r' || body[pos] == '\n')) {
    ++pos;
  }
  if (pos >= body.size() || body[pos] != '"') return {};
  ++pos;  // skip opening '"'
  const auto end = body.find('"', pos);
  if (end == std::string::npos) return {};
  return body.substr(pos, end - pos);
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

// Find position right after "key": [ (array open), whitespace-tolerant.
static std::size_t jarray_start(const std::string& body, const char* key,
                                  std::size_t from = 0) {
  const std::string pat = std::string("\"") + key + "\":";
  auto pos = body.find(pat, from);
  if (pos == std::string::npos) return std::string::npos;
  pos += pat.size();
  while (pos < body.size() &&
         (body[pos] == ' ' || body[pos] == '\t' ||
          body[pos] == '\r' || body[pos] == '\n')) {
    ++pos;
  }
  if (pos >= body.size() || body[pos] != '[') return std::string::npos;
  return pos + 1;  // position right after '['
}

// Extract bare (unquoted) number: "key": 22.5 or "key":3
// Used for Open-Meteo / ip-api.com responses that don't quote numbers.
static std::string jbare(const std::string& body, const char* key,
                          std::size_t from = 0) {
  const std::string pat = std::string("\"") + key + "\":";
  auto pos = body.find(pat, from);
  if (pos == std::string::npos) return {};
  pos += pat.size();
  while (pos < body.size() &&
         (body[pos] == ' ' || body[pos] == '\t' ||
          body[pos] == '\r' || body[pos] == '\n')) {
    ++pos;
  }
  const auto start = pos;
  while (pos < body.size() &&
         (body[pos] == '-' || body[pos] == '.' ||
          (body[pos] >= '0' && body[pos] <= '9'))) {
    ++pos;
  }
  return body.substr(start, pos - start);
}

// Parse a decimal string (possibly with fractional part) into int via lround.
// No exceptions: all parsing is manual.
static int parse_decimal_int(const std::string& s) {
  if (s.empty()) return 0;
  std::size_t i = 0;
  bool negative = false;
  if (s[i] == '-') { negative = true; ++i; }

  long long int_part = 0;
  while (i < s.size() && s[i] >= '0' && s[i] <= '9') {
    int_part = int_part * 10 + (s[i] - '0');
    ++i;
  }
  // Fractional part: round at first decimal digit.
  int frac_first = 0;
  if (i < s.size() && s[i] == '.') {
    ++i;
    if (i < s.size() && s[i] >= '0' && s[i] <= '9') {
      frac_first = s[i] - '0';
    }
  }
  long long rounded = int_part;
  if (frac_first >= 5) ++rounded;
  return static_cast<int>(negative ? -rounded : rounded);
}

static int jbare_int(const std::string& body, const char* key,
                     std::size_t from = 0) {
  const std::string s = jbare(body, key, from);
  if (s.empty()) return 0;
  return parse_decimal_int(s);
}

// Nth element (0-based) of a bare-number JSON array: "key":[1.5, 2, 3]
static int jarray_nth_int(const std::string& body, const char* key, int n,
                           std::size_t from = 0) {
  const std::size_t arr = jarray_start(body, key, from);
  if (arr == std::string::npos) return 0;
  std::size_t pos = arr;
  for (int i = 0; i < n; ++i) {
    const auto comma = body.find(',', pos);
    if (comma == std::string::npos) return 0;
    pos = comma + 1;
  }
  while (pos < body.size() &&
         (body[pos] == ' ' || body[pos] == '\t' ||
          body[pos] == '\r' || body[pos] == '\n')) {
    ++pos;
  }
  const auto start = pos;
  while (pos < body.size() &&
         (body[pos] == '-' || body[pos] == '.' ||
          (body[pos] >= '0' && body[pos] <= '9'))) {
    ++pos;
  }
  return parse_decimal_int(body.substr(start, pos - start));
}

// ── Weather code mapping — wttr.in ───────────────────────────────────────────
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
static constexpr CodeEntry kWttrCodeTable[] = {
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

// ── Weather code mapping — Open-Meteo (standard WMO codes) ──────────────────
static constexpr CodeEntry kOpenMeteoCodeTable[] = {
  {0,  "Sunny",                    "sunny"},
  {1,  "Mainly Sunny",             "sunny"},
  {2,  "Partly Cloudy",            "partly_cloudy"},
  {3,  "Overcast",                 "cloudy"},
  {45, "Fog",                      "fog"},
  {48, "Freezing Fog",             "fog"},
  {51, "Light Drizzle",            "drizzle"},
  {53, "Drizzle",                  "drizzle"},
  {55, "Heavy Drizzle",            "drizzle"},
  {56, "Freezing Drizzle",         "drizzle"},
  {57, "Heavy Freezing Drizzle",   "drizzle"},
  {61, "Light Rain",               "rain"},
  {63, "Rain",                     "rain"},
  {65, "Heavy Rain",               "rain"},
  {66, "Freezing Rain",            "rain"},
  {67, "Heavy Freezing Rain",      "rain"},
  {71, "Light Snow",               "snow"},
  {73, "Snow",                     "snow"},
  {75, "Heavy Snow",               "snow"},
  {77, "Snow Grains",              "snow"},
  {80, "Rain Shower",              "rain"},
  {81, "Rain Shower",              "rain"},
  {82, "Heavy Rain Shower",        "rain"},
  {85, "Snow Shower",              "snow"},
  {86, "Heavy Snow Shower",        "snow"},
  {95, "Thunderstorm",             "thunderstorm"},
  {96, "Thunderstorm w/ Hail",     "thunderstorm"},
  {99, "Heavy Thunderstorm",       "thunderstorm"},
};
// clang-format on

static const CodeEntry* lookup_wttr_code(int code) {
  for (const auto& e : kWttrCodeTable) {
    if (e.code == code) return &e;
  }
  return nullptr;
}

static const CodeEntry* lookup_openmeteo_code(int code) {
  for (const auto& e : kOpenMeteoCodeTable) {
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

// ── Forecast day parser (wttr.in) ─────────────────────────────────────────────
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

// ── Simple HTTP GET helper ────────────────────────────────────────────────────

static bool http_get(const char* url, uint32_t timeout_ms) {
  g_body.clear();
  esp_http_client_config_t cfg{};
  cfg.url           = url;
  cfg.event_handler = on_data;
  cfg.timeout_ms    = static_cast<int>(timeout_ms);
  auto* client = esp_http_client_init(&cfg);
  if (!client) return false;
  const esp_err_t err    = esp_http_client_perform(client);
  const int       status = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);
  if (err != ESP_OK) {
    ESP_LOGW(kTag, "http_get %s: %s", url, esp_err_to_name(err));
    return false;
  }
  if (status != 200) {
    ESP_LOGW(kTag, "http_get %s: status %d", url, status);
    return false;
  }
  return true;
}

// ── Primary: wttr.in ─────────────────────────────────────────────────────────

static WeatherResult weather_fetch_wttr(uint32_t timeout_ms) {
  WeatherResult result;
  g_body.reserve(8192);  // wttr.in j1 responses are typically 6–8 KB

  if (!http_get("http://wttr.in?format=j1", timeout_ms)) {
    result.error = "http_" + std::to_string(0);  // replaced below
    // Re-derive the error string from the last status (already logged above).
    // We just mark it failed so the caller can try the fallback.
    result.error = "wttr: request failed";
    return result;
  }

  // ── Current conditions ──────────────────────────────────────────────────
  const int code = jint(g_body, "weatherCode");
  result.temperature_c    = jint(g_body, "temp_C");
  result.feels_like_c     = jint(g_body, "FeelsLikeC");
  result.humidity_percent = jint(g_body, "humidity");
  result.wind_kmh         = jint(g_body, "windspeedKmph");
  result.uv_index         = jint(g_body, "uvIndex");

  const auto* entry = lookup_wttr_code(code);
  result.condition = entry ? entry->label   : "Cloudy";
  result.icon_key  = entry ? entry->icon_key : "cloudy";

  // ── Location ────────────────────────────────────────────────────────────
  {
    const std::size_t area_pos = g_body.find("\"areaName\"");
    if (area_pos != std::string::npos) {
      result.location = jstr(g_body, "value", area_pos);
    }
    if (result.location.empty()) result.location = "Unknown";
  }

  // ── Today hi/lo ─────────────────────────────────────────────────────────
  const std::size_t weather_arr = jarray_start(g_body, "weather");
  if (weather_arr != std::string::npos) {
    result.hi_c = jint(g_body, "maxtempC", weather_arr);
    result.lo_c = jint(g_body, "mintempC", weather_arr);
  }

  // ── 3-day forecast ───────────────────────────────────────────────────────
  for (int day = 0; day < 3; ++day) {
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

    const std::size_t hourly_pos = jarray_start(g_body, "hourly", pos);
    const int day_code = hourly_pos != std::string::npos
                             ? jint(g_body, "weatherCode", hourly_pos)
                             : 0;
    const auto* de = lookup_wttr_code(day_code);
    fd.condition = de ? de->label   : "Cloudy";
    fd.icon_key  = de ? de->icon_key : "cloudy";
  }

  result.ok = true;
  ESP_LOGI(kTag, "OK (wttr): %s  %s  %d°C  humidity=%d%%  wind=%d km/h  UV=%d",
           result.location.c_str(), result.condition.c_str(),
           result.temperature_c, result.humidity_percent,
           result.wind_kmh, result.uv_index);
  return result;
}

// ── Fallback: ip-api.com geolocation + Open-Meteo weather ────────────────────

static WeatherResult weather_fetch_openmeteo(uint32_t timeout_ms) {
  WeatherResult result;

  // Step 1: IP geolocation — returns lat, lon, city (no API key needed)
  g_body.reserve(512);
  if (!http_get("http://ip-api.com/json/?fields=status,lat,lon,city", timeout_ms / 2)) {
    result.error = "openmeteo: geolocation failed";
    return result;
  }

  const std::string geo = g_body;  // save before next request overwrites g_body

  if (jstr(geo, "status") != "success") {
    result.error = "openmeteo: geo status != success";
    ESP_LOGW(kTag, "%s", result.error.c_str());
    return result;
  }

  const std::string lat_s = jbare(geo, "lat");
  const std::string lon_s = jbare(geo, "lon");
  result.location = jstr(geo, "city");
  if (result.location.empty()) result.location = "Unknown";

  if (lat_s.empty() || lon_s.empty()) {
    result.error = "openmeteo: no lat/lon in geo response";
    ESP_LOGW(kTag, "%s", result.error.c_str());
    return result;
  }
  ESP_LOGI(kTag, "Geolocation: %s (lat=%s lon=%s)",
           result.location.c_str(), lat_s.c_str(), lon_s.c_str());

  // Step 2: Weather from Open-Meteo (free, no API key, uses standard WMO codes)
  const std::string wx_url =
      std::string("http://api.open-meteo.com/v1/forecast") +
      "?latitude=" + lat_s +
      "&longitude=" + lon_s +
      "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code" +
      "&daily=weather_code,temperature_2m_max,temperature_2m_min" +
      "&forecast_days=3&wind_speed_unit=kmh&timezone=auto";

  g_body.clear();
  g_body.reserve(4096);
  if (!http_get(wx_url.c_str(), timeout_ms)) {
    result.error = "openmeteo: weather request failed";
    return result;
  }

  // ── Current conditions ──────────────────────────────────────────────────
  const std::size_t curr_pos = g_body.find("\"current\"");
  result.temperature_c    = jbare_int(g_body, "temperature_2m",        curr_pos);
  result.feels_like_c     = result.temperature_c;  // not in free tier
  result.humidity_percent = jbare_int(g_body, "relative_humidity_2m",  curr_pos);
  result.wind_kmh         = jbare_int(g_body, "wind_speed_10m",        curr_pos);
  result.uv_index         = 0;  // not in free tier current endpoint
  const int curr_code     = jbare_int(g_body, "weather_code",          curr_pos);

  const auto* entry = lookup_openmeteo_code(curr_code);
  result.condition = entry ? entry->label    : "Cloudy";
  result.icon_key  = entry ? entry->icon_key : "cloudy";

  // ── Daily hi/lo and 3-day forecast ──────────────────────────────────────
  const std::size_t daily_pos = g_body.find("\"daily\"");
  if (daily_pos != std::string::npos) {
    result.hi_c = jarray_nth_int(g_body, "temperature_2m_max", 0, daily_pos);
    result.lo_c = jarray_nth_int(g_body, "temperature_2m_min", 0, daily_pos);

    for (int day = 0; day < 3; ++day) {
      auto& fd    = result.forecast[static_cast<std::size_t>(day)];
      fd.dow      = day_name(day);
      fd.hi_c     = jarray_nth_int(g_body, "temperature_2m_max", day, daily_pos);
      fd.lo_c     = jarray_nth_int(g_body, "temperature_2m_min", day, daily_pos);
      const int day_code = jarray_nth_int(g_body, "weather_code", day, daily_pos);
      const auto* de = lookup_openmeteo_code(day_code);
      fd.condition = de ? de->label    : "Cloudy";
      fd.icon_key  = de ? de->icon_key : "cloudy";
    }
  }

  result.ok = true;
  ESP_LOGI(kTag, "OK (openmeteo): %s  %s  %d°C  humidity=%d%%  wind=%d km/h",
           result.location.c_str(), result.condition.c_str(),
           result.temperature_c, result.humidity_percent, result.wind_kmh);
  return result;
}

}  // namespace

// ── Public API ────────────────────────────────────────────────────────────────

WeatherResult weather_fetch(uint32_t timeout_ms) {
  WeatherResult result = weather_fetch_wttr(timeout_ms);
  if (!result.ok) {
    ESP_LOGW(kTag, "wttr.in failed (%s), trying Open-Meteo fallback...",
             result.error.c_str());
    result = weather_fetch_openmeteo(timeout_ms);
  }
  return result;
}

}  // namespace fridge_ink::platform
