#pragma once

#include <cstddef>
#include <string>

namespace fridge_ink::platform {

// ── Persistent application state ───────────────────────────────────────────
// Stored in NVS under the "fridge_ink" namespace.  All fields are optional:
// missing keys produce the zero/empty default, so the app starts clean on
// first boot or after a wipe.
struct PersistentState {
  bool        setup_completed{false};
  std::string wifi_ssid{};
  std::string timezone{};
  std::size_t language_index{0};   // 0=en-US, 1=zh-CN, 2=…
};

// Load from NVS.  Returns all-defaults if NVS is empty or has never been
// written (e.g. first boot, after nvs_flash_erase, after persistent_erase).
PersistentState persistent_load();

// Write state to NVS and commit.  No-op if NVS is unavailable.
void persistent_save(const PersistentState& state);

// Erase all keys in the "fridge_ink" NVS namespace (factory reset).
void persistent_erase();

}  // namespace fridge_ink::platform
