#include "platform/ntp_sync.hpp"
#include "platform/clock.hpp"

#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_sntp.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <cinttypes>
#include <cstdlib>
#include <cstring>
#include <string>

namespace fridge_ink::platform {

namespace {

static const char* kTag = "ntp_sync";

// ── NTP sync ─────────────────────────────────────────────────────────────────

bool do_ntp_sync(uint32_t timeout_ms) {
  // Already synced and wall clock is valid — nothing to do.
  if (esp_sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED &&
      wall_time_is_valid()) {
    ESP_LOGI(kTag, "Wall clock already valid — skipping NTP init");
    return true;
  }

  // Use POLL mode so the client actively sends a request.
  // After the response arrives we call esp_sntp_stop() immediately so lwIP
  // never schedules the next hourly poll — keeping the WiFi radio quiet.
  esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
  esp_sntp_setservername(0, "pool.ntp.org");
  esp_sntp_setservername(1, "time.cloudflare.com");
  esp_sntp_setservername(2, "ntp.aliyun.com");  // low-latency in China
  esp_sntp_init();

  ESP_LOGI(kTag, "Waiting for NTP sync (timeout %" PRIu32 " ms)…", timeout_ms);

  constexpr uint32_t kStepMs = 200;
  for (uint32_t elapsed = 0; elapsed < timeout_ms; elapsed += kStepMs) {
    if (esp_sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED &&
        wall_time_is_valid()) {
      // Stop SNTP immediately — prevents lwIP from scheduling the next
      // hourly poll and keeps the WiFi radio idle between voice requests.
      esp_sntp_stop();
      const std::time_t t = wall_time_seconds();
      const struct tm* lt = localtime(&t);
      ESP_LOGI(kTag, "NTP synced — UTC %04d-%02d-%02d %02d:%02d:%02d",
               lt->tm_year + 1900, lt->tm_mon + 1, lt->tm_mday,
               lt->tm_hour, lt->tm_min, lt->tm_sec);
      return true;
    }
    vTaskDelay(pdMS_TO_TICKS(kStepMs));
  }

  esp_sntp_stop();  // clean up even on timeout — no lingering background task
  ESP_LOGW(kTag, "NTP sync timed out after %" PRIu32 " ms", timeout_ms);
  return false;
}

// ── ip-api.com geolocation ───────────────────────────────────────────────────

static std::string g_ip_api_body;

static esp_err_t on_http_data(esp_http_client_event_t* evt) {
  if (evt->event_id == HTTP_EVENT_ON_DATA && evt->data_len > 0) {
    g_ip_api_body.append(static_cast<const char*>(evt->data),
                         static_cast<std::size_t>(evt->data_len));
  }
  return ESP_OK;
}

// Extract a quoted string value: "key":"<value>"
static std::string json_str(const std::string& body, const char* key) {
  const std::string search = std::string("\"") + key + "\":\"";
  const auto pos = body.find(search);
  if (pos == std::string::npos) return {};
  const auto start = pos + search.size();
  const auto end   = body.find('"', start);
  if (end == std::string::npos) return {};
  return body.substr(start, end - start);
}

// Extract a numeric value (integer, possibly negative): "key":<n>
static int json_int(const std::string& body, const char* key) {
  const std::string search = std::string("\"") + key + "\":";
  auto pos = body.find(search);
  if (pos == std::string::npos) return 0;
  pos += search.size();
  while (pos < body.size() && body[pos] == ' ') ++pos;
  bool neg = false;
  if (pos < body.size() && body[pos] == '-') { neg = true; ++pos; }
  int val = 0;
  while (pos < body.size() && body[pos] >= '0' && body[pos] <= '9') {
    val = val * 10 + (body[pos++] - '0');
  }
  return neg ? -val : val;
}

// Build a simple POSIX TZ string from a UTC offset (seconds).
// Note: POSIX sign convention is inverted (UTC+8 → "UTC-8").
static std::string posix_from_offset(int offset_seconds) {
  const int abs_s = offset_seconds < 0 ? -offset_seconds : offset_seconds;
  const int h     = abs_s / 3600;
  const int m     = (abs_s % 3600) / 60;
  // POSIX: positive offset means west of UTC, so flip.
  const int posix_h = (offset_seconds >= 0) ? -h : h;
  char buf[32];
  if (m == 0) {
    snprintf(buf, sizeof(buf), "UTC%+d", posix_h);
  } else {
    snprintf(buf, sizeof(buf), "UTC%+d:%02d", posix_h, m);
  }
  return buf;
}

std::string do_detect_timezone(uint32_t timeout_ms) {
  g_ip_api_body.clear();
  g_ip_api_body.reserve(128);

  esp_http_client_config_t cfg{};
  cfg.url           = "http://ip-api.com/json?fields=status,timezone,offset";
  cfg.event_handler = on_http_data;
  cfg.timeout_ms    = static_cast<int>(timeout_ms);

  auto* client = esp_http_client_init(&cfg);
  if (!client) {
    ESP_LOGE(kTag, "ip-api: failed to create HTTP client");
    return {};
  }

  const esp_err_t err    = esp_http_client_perform(client);
  const int       status = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);

  if (err != ESP_OK) {
    ESP_LOGW(kTag, "ip-api: HTTP perform error: %s", esp_err_to_name(err));
    return {};
  }
  if (status != 200) {
    ESP_LOGW(kTag, "ip-api: HTTP status %d", status);
    return {};
  }

  ESP_LOGD(kTag, "ip-api body: %s", g_ip_api_body.c_str());

  if (json_str(g_ip_api_body, "status") != "success") {
    ESP_LOGW(kTag, "ip-api: response status != success");
    return {};
  }

  const std::string iana   = json_str(g_ip_api_body, "timezone");
  const int         offset = json_int(g_ip_api_body, "offset");

  ESP_LOGI(kTag, "ip-api: timezone=\"%s\"  offset=%d s", iana.c_str(), offset);

  if (!iana.empty()) {
    if (apply_timezone(iana)) {
      return iana;
    }
    // IANA name not in built-in table — fall back to numeric offset.
    ESP_LOGW(kTag, "IANA '%s' not in table — applying UTC offset %d s",
             iana.c_str(), offset);
  }

  // Numeric offset fallback (also covers the case where the response has
  // an offset but no timezone name).
  const std::string posix = posix_from_offset(offset);
  ESP_LOGI(kTag, "Applying POSIX TZ fallback: %s", posix.c_str());
  setenv("TZ", posix.c_str(), 1);
  tzset();

  return iana;  // may be empty if the response had no name
}

}  // namespace

// ── Public API ───────────────────────────────────────────────────────────────

bool ntp_sync_time(uint32_t timeout_ms) {
  return do_ntp_sync(timeout_ms);
}

std::string ntp_detect_and_apply_timezone(uint32_t timeout_ms) {
  return do_detect_timezone(timeout_ms);
}

bool ntp_sync(uint32_t timeout_ms) {
  // 60 % of budget for NTP, 40 % for timezone detection.
  const uint32_t ntp_budget = timeout_ms * 6 / 10;
  const uint32_t tz_budget  = timeout_ms - ntp_budget;

  const bool time_ok = ntp_sync_time(ntp_budget);
  if (time_ok) {
    ntp_detect_and_apply_timezone(tz_budget);
  } else {
    ESP_LOGW(kTag, "Time sync failed — skipping timezone detection");
  }
  return time_ok;
}

}  // namespace fridge_ink::platform
