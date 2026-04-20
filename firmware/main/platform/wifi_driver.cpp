#include "platform/wifi_driver.hpp"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"

#include <cstring>

namespace fridge_ink::platform {
namespace {

static const char* kTag = "wifi_driver";

// Event group bits.
static constexpr EventBits_t kConnectedBit  = BIT0;
static constexpr EventBits_t kFailedBit     = BIT1;

static EventGroupHandle_t g_events     = nullptr;
static bool               g_initialised = false;
static bool               g_connected   = false;
static bool               g_stop_retry  = false;  // set after connect() gives up

static void wifi_event_handler(void* /*arg*/, esp_event_base_t base,
                                int32_t id, void* /*data*/) {
  if (base == WIFI_EVENT) {
    if (id == WIFI_EVENT_STA_START) {
      esp_wifi_connect();
    } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
      g_connected = false;
      ESP_LOGW(kTag, "Disconnected — retrying…");
      esp_wifi_connect();
    }
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    const auto* evt = static_cast<ip_event_got_ip_t*>(/*data*/ nullptr);
    (void)evt;
    g_connected = true;
    ESP_LOGI(kTag, "Got IP address");
    if (g_events) {
      xEventGroupSetBits(g_events, kConnectedBit);
    }
  }
}

// Re-declare handler with proper data pointer (the one above ignores data
// for simplicity; this one is the real callback registered with esp_event).
static void wifi_event_cb(void* arg, esp_event_base_t base,
                           int32_t id, void* data) {
  if (base == WIFI_EVENT) {
    if (id == WIFI_EVENT_STA_START) {
      ESP_LOGI(kTag, "STA started — connecting…");
      esp_wifi_connect();
    } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
      g_connected = false;
      const auto* disc =
          static_cast<wifi_event_sta_disconnected_t*>(data);
      if (g_stop_retry) {
        ESP_LOGD(kTag, "Disconnected (reason=%d) — not retrying (gave up)", disc->reason);
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

}  // namespace

bool wifi_connect(const char* ssid, const char* password,
                  uint32_t timeout_ms) {
  if (!ssid || ssid[0] == '\0') {
    ESP_LOGW(kTag, "wifi_connect: no SSID configured — skipping");
    return false;
  }

  if (g_initialised) {
    ESP_LOGW(kTag, "wifi_connect: already initialised");
    return g_connected;
  }

  // ── NVS (required by WiFi driver) ────────────────────────────────────────
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
      err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGW(kTag, "NVS partition erased and re-initialised");
    nvs_flash_erase();
    err = nvs_flash_init();
  }
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "nvs_flash_init failed: %s", esp_err_to_name(err));
    return false;
  }

  // ── TCP/IP stack + default event loop ────────────────────────────────────
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  // ── WiFi driver ───────────────────────────────────────────────────────────
  wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

  g_events = xEventGroupCreate();

  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_cb, nullptr, nullptr));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_cb, nullptr, nullptr));

  // ── Station config ────────────────────────────────────────────────────────
  wifi_config_t wifi_cfg{};
  strncpy(reinterpret_cast<char*>(wifi_cfg.sta.ssid),
          ssid, sizeof(wifi_cfg.sta.ssid) - 1);
  if (password && password[0] != '\0') {
    strncpy(reinterpret_cast<char*>(wifi_cfg.sta.password),
            password, sizeof(wifi_cfg.sta.password) - 1);
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
  }

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
  ESP_ERROR_CHECK(esp_wifi_start());

  g_initialised = true;
  ESP_LOGI(kTag, "Connecting to SSID: %s", ssid);

  // ── Wait for IP ───────────────────────────────────────────────────────────
  const EventBits_t bits = xEventGroupWaitBits(
      g_events, kConnectedBit | kFailedBit,
      pdFALSE, pdFALSE,
      pdMS_TO_TICKS(timeout_ms));

  if (bits & kConnectedBit) {
    ESP_LOGI(kTag, "WiFi connected successfully");
    return true;
  }

  // Timed out — stop the retry loop so we don't spam the log forever.
  g_stop_retry = true;
  ESP_LOGW(kTag, "WiFi connection timed out after %" PRIu32 " ms — retries stopped", timeout_ms);
  return false;
}

bool wifi_is_connected() {
  return g_connected;
}

void wifi_disconnect() {
  if (!g_initialised) return;
  esp_wifi_disconnect();
  esp_wifi_stop();
  esp_wifi_deinit();
  g_initialised = false;
  g_connected   = false;
  g_stop_retry  = false;
  ESP_LOGI(kTag, "WiFi disconnected");
}

}  // namespace fridge_ink::platform
