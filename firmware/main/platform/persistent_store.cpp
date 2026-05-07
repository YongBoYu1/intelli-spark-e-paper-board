#include "platform/persistent_store.hpp"

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

#include <cstring>

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag       = "nvs_store";
constexpr const char* kNamespace = "fridge_ink";

// NVS keys — keep short (max 15 chars per ESP-IDF constraint).
constexpr const char* kKeySetupDone = "setup_done";   // u8
constexpr const char* kKeyWifiSsid  = "wifi_ssid";    // str
constexpr const char* kKeyTimezone  = "timezone";     // str
constexpr const char* kKeyLang      = "lang";         // u8

// Read a NVS string into a std::string.  Returns empty string on any error.
std::string nvs_read_string(nvs_handle_t h, const char* key) {
  size_t len = 0;
  if (nvs_get_str(h, key, nullptr, &len) != ESP_OK || len == 0) {
    return {};
  }
  std::string buf(len, '\0');
  if (nvs_get_str(h, key, &buf[0], &len) != ESP_OK) {
    return {};
  }
  // nvs_get_str includes the NUL terminator in `len`; strip it.
  while (!buf.empty() && buf.back() == '\0') {
    buf.pop_back();
  }
  return buf;
}

}  // namespace

PersistentState persistent_load() {
  PersistentState out{};
  nvs_handle_t h;
  if (nvs_open(kNamespace, NVS_READONLY, &h) != ESP_OK) {
    // Namespace doesn't exist yet — first boot or after erase.
    return out;
  }

  uint8_t setup_done = 0;
  nvs_get_u8(h, kKeySetupDone, &setup_done);
  out.setup_completed = (setup_done != 0);

  out.wifi_ssid       = nvs_read_string(h, kKeyWifiSsid);
  out.timezone        = nvs_read_string(h, kKeyTimezone);

  uint8_t lang = 0;
  nvs_get_u8(h, kKeyLang, &lang);
  out.language_index = static_cast<std::size_t>(lang);

  nvs_close(h);

  ESP_LOGI(kTag, "loaded: setup_completed=%d wifi_ssid=%s timezone=%s lang=%u",
           static_cast<int>(out.setup_completed),
           out.wifi_ssid.c_str(),
           out.timezone.c_str(),
           static_cast<unsigned>(out.language_index));
  return out;
}

void persistent_save(const PersistentState& state) {
  nvs_handle_t h;
  if (nvs_open(kNamespace, NVS_READWRITE, &h) != ESP_OK) {
    ESP_LOGW(kTag, "nvs_open(RW) failed — state not persisted");
    return;
  }

  nvs_set_u8(h, kKeySetupDone, state.setup_completed ? 1U : 0U);
  nvs_set_str(h, kKeyWifiSsid, state.wifi_ssid.c_str());
  nvs_set_str(h, kKeyTimezone, state.timezone.c_str());
  nvs_set_u8(h, kKeyLang, static_cast<uint8_t>(state.language_index));

  const esp_err_t err = nvs_commit(h);
  if (err != ESP_OK) {
    ESP_LOGW(kTag, "nvs_commit failed: %s", esp_err_to_name(err));
  } else {
    ESP_LOGI(kTag, "saved: setup_completed=%d wifi_ssid=%s timezone=%s lang=%u",
             static_cast<int>(state.setup_completed),
             state.wifi_ssid.c_str(),
             state.timezone.c_str(),
             static_cast<unsigned>(state.language_index));
  }
  nvs_close(h);
}

void persistent_erase() {
  nvs_handle_t h;
  if (nvs_open(kNamespace, NVS_READWRITE, &h) != ESP_OK) {
    return;
  }
  nvs_erase_all(h);
  nvs_commit(h);
  nvs_close(h);
  ESP_LOGI(kTag, "NVS namespace erased (factory reset)");
}

}  // namespace fridge_ink::platform
