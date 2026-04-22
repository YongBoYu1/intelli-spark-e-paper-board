#include "platform/wifi_driver.hpp"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"

#include <algorithm>
#include <cstring>

namespace fridge_ink::platform {
namespace {

static const char* kTag = "wifi_driver";

// Event group bits.
static constexpr EventBits_t kConnectedBit = BIT0;
static constexpr EventBits_t kFailedBit    = BIT1;

static EventGroupHandle_t g_events      = nullptr;
static bool               g_stack_ready = false;  // WiFi driver started
static bool               g_scan_only   = false;  // started for scan, not connecting
static bool               g_connected   = false;
static bool               g_stop_retry  = false;

static void wifi_event_cb(void* /*arg*/, esp_event_base_t base,
                          int32_t id, void* data) {
  if (base == WIFI_EVENT) {
    if (id == WIFI_EVENT_STA_START) {
      if (!g_scan_only) {
        ESP_LOGI(kTag, "STA started — connecting…");
        esp_wifi_connect();
      } else {
        ESP_LOGI(kTag, "STA started — scan mode");
      }
    } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
      g_connected = false;
      const auto* disc = static_cast<wifi_event_sta_disconnected_t*>(data);
      if (g_scan_only || g_stop_retry) {
        ESP_LOGD(kTag, "Disconnected (reason=%d) — not retrying", disc->reason);
      } else {
        ESP_LOGW(kTag, "Disconnected (reason=%d) — retrying", disc->reason);
        esp_wifi_connect();
      }
    }
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    const auto* evt = static_cast<ip_event_got_ip_t*>(data);
    ESP_LOGI(kTag, "Got IP: " IPSTR, IP2STR(&evt->ip_info.ip));
    g_connected = true;
    if (g_events) xEventGroupSetBits(g_events, kConnectedBit);
  }
}

// ── Shared initialisation ─────────────────────────────────────────────────────
// Idempotent: safe to call when already started.  Sets g_scan_only = true so
// the event handler does not trigger an immediate connect attempt.
static bool wifi_stack_init() {
  if (g_stack_ready) return true;

  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGW(kTag, "NVS partition erased and re-initialised");
    nvs_flash_erase();
    err = nvs_flash_init();
  }
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "nvs_flash_init failed: %s", esp_err_to_name(err));
    return false;
  }

  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

  g_events = xEventGroupCreate();

  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_cb, nullptr, nullptr));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_cb, nullptr, nullptr));

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));

  g_scan_only   = true;   // start in scan-only mode; connect call will clear this
  g_stack_ready = true;

  ESP_ERROR_CHECK(esp_wifi_start());
  return true;
}

}  // namespace

// ── Scan ─────────────────────────────────────────────────────────────────────

std::vector<WifiApInfo> wifi_scan_networks(uint32_t timeout_ms) {
  if (!wifi_stack_init()) return {};

  wifi_scan_config_t scan_cfg{};
  scan_cfg.show_hidden = false;

  const esp_err_t err = esp_wifi_scan_start(&scan_cfg, /*block=*/true);
  if (err != ESP_OK) {
    ESP_LOGW(kTag, "wifi_scan_start failed: %s", esp_err_to_name(err));
    return {};
  }
  (void)timeout_ms;  // scan_start with block=true already waits internally

  uint16_t num = 0;
  esp_wifi_scan_get_ap_num(&num);
  if (num == 0) return {};

  std::vector<wifi_ap_record_t> records(num);
  esp_wifi_scan_get_ap_records(&num, records.data());

  std::vector<WifiApInfo> result;
  result.reserve(num);
  for (uint16_t i = 0; i < num; ++i) {
    const auto& r = records[i];
    const char* ssid_str = reinterpret_cast<const char*>(r.ssid);
    if (ssid_str[0] == '\0') continue;  // skip hidden SSIDs
    WifiApInfo ap;
    ap.ssid = ssid_str;
    ap.rssi = static_cast<int>(r.rssi);
    result.push_back(std::move(ap));
  }
  // Sort strongest first.
  std::sort(result.begin(), result.end(),
            [](const WifiApInfo& a, const WifiApInfo& b) {
              return a.rssi > b.rssi;
            });
  return result;
}

// ── Connect to a specific AP ──────────────────────────────────────────────────
// May be called after wifi_scan_networks() has already started the driver.

bool wifi_connect_to(const char* ssid, const char* password,
                     uint32_t timeout_ms) {
  if (!ssid || ssid[0] == '\0') {
    ESP_LOGW(kTag, "wifi_connect_to: empty SSID");
    return false;
  }
  if (!wifi_stack_init()) return false;

  // Disconnect any existing association before reconfiguring.
  // ESP-IDF rejects esp_wifi_connect() with "sta is connected" if skipped.
  g_stop_retry = true;   // suppress the disconnect-handler retry during teardown
  esp_wifi_disconnect();
  vTaskDelay(pdMS_TO_TICKS(100));  // brief settle so STA_DISCONNECTED fires first

  // Switch out of scan-only mode so the disconnect handler retries.
  g_scan_only  = false;
  g_stop_retry = false;
  g_connected  = false;
  if (g_events) xEventGroupClearBits(g_events, kConnectedBit | kFailedBit);

  wifi_config_t cfg{};
  strncpy(reinterpret_cast<char*>(cfg.sta.ssid),
          ssid, sizeof(cfg.sta.ssid) - 1);
  if (password && password[0] != '\0') {
    strncpy(reinterpret_cast<char*>(cfg.sta.password),
            password, sizeof(cfg.sta.password) - 1);
    cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
  }

  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
  ESP_LOGI(kTag, "Connecting to SSID: %s", ssid);
  esp_wifi_connect();

  const EventBits_t bits = xEventGroupWaitBits(
      g_events, kConnectedBit | kFailedBit,
      pdFALSE, pdFALSE, pdMS_TO_TICKS(timeout_ms));

  if (bits & kConnectedBit) {
    ESP_LOGI(kTag, "WiFi connected successfully");
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
    return true;
  }

  g_stop_retry = true;
  ESP_LOGW(kTag, "WiFi connect_to timed out after %" PRIu32 " ms", timeout_ms);
  return false;
}

// ── Legacy entry-point (compile-time credentials) ────────────────────────────

bool wifi_connect(const char* ssid, const char* password,
                  uint32_t timeout_ms) {
  if (!ssid || ssid[0] == '\0') {
    ESP_LOGW(kTag, "wifi_connect: no SSID configured — skipping");
    return false;
  }
  // If the stack was already started for scanning, use connect_to path.
  // If fully connected, just report status.
  if (g_stack_ready && !g_scan_only) {
    ESP_LOGW(kTag, "wifi_connect: already initialised");
    return g_connected;
  }
  return wifi_connect_to(ssid, password, timeout_ms);
}

bool wifi_is_connected() {
  return g_connected;
}

void wifi_disconnect() {
  if (!g_stack_ready) return;
  esp_wifi_disconnect();
  esp_wifi_stop();
  esp_wifi_deinit();
  g_stack_ready = false;
  g_scan_only   = false;
  g_connected   = false;
  g_stop_retry  = false;
  ESP_LOGI(kTag, "WiFi disconnected");
}

}  // namespace fridge_ink::platform
