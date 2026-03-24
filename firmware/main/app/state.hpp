#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace fridge_ink::app {

enum class Screen {
  Landing,
  Onboarding,
  Home,
};

enum class Language {
  EnUs,
  EsEs,
  FrFr,
};

struct DashboardSummary {
  std::string location{"Kitchen"};
  int battery_percent{84};
  int reminder_count{3};
};

struct LandingState {
  bool rotate_seen{false};
  std::size_t language_index{0};
  std::string status{};
};

struct HomeState {
  int focused_index{0};
};

struct OnboardingState {
  std::size_t step_index{0};
  std::size_t start_focus_index{0};
  std::size_t qr_focus_index{0};
  std::size_t prefs_focus_index{0};
  std::string pair_token{"A1B2-C3D4"};
  std::string wifi_ssid{};
  std::string timezone{"America/Toronto"};
  bool auto_sync_enabled{true};
  std::string status{};
};

struct AppState {
  Screen screen{Screen::Landing};
  bool setup_completed{false};
  Language device_language{Language::EnUs};
  Language voice_locale{Language::EnUs};
  std::uint64_t boot_started_ms{0};
  std::uint64_t last_tick_ms{0};
  LandingState landing{};
  OnboardingState onboarding{};
  HomeState home{};
  DashboardSummary dashboard{};
};

const char* screen_name(Screen screen);
const char* language_code(Language language);
const char* language_label(Language language);
Language language_from_index(std::size_t index);
std::size_t language_index(Language language);

}  // namespace fridge_ink::app
