#pragma once

namespace fridge_ink::app {

// ── Build-mode flag ────────────────────────────────────────────────────────
// Set to `true` for developer / demo / QA builds.
//   → Dashboard is pre-populated with realistic sample data so every screen
//     can be exercised without going through setup or a live data sync.
//
// Set to `false` for retail / production builds.
//   → Dashboard starts completely empty.  All content comes from the user's
//     own setup (WiFi onboarding + cloud sync) after first boot.
//
// To toggle: change the value below and rebuild.  No other file needs to
// change.
constexpr bool kDeveloperMode = false;

}  // namespace fridge_ink::app
