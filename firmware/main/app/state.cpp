#include "app/state.hpp"

namespace fridge_ink::app {

const char* screen_name(Screen screen) {
  switch (screen) {
    case Screen::Landing:
      return "landing";
    case Screen::Onboarding:
      return "onboarding";
    case Screen::Home:
      return "home";
    case Screen::Menu:
      return "menu";
    case Screen::Timer:
      return "timer";
    case Screen::Calendar:
      return "calendar";
    case Screen::Weather:
      return "weather";
    case Screen::Inventory:
      return "inventory";
    case Screen::Settings:
      return "settings";
  }
  return "landing";
}

const char* language_code(Language language) {
  switch (language) {
    case Language::EnUs:
      return "en-US";
    case Language::EsEs:
      return "es-ES";
    case Language::FrFr:
      return "fr-FR";
  }
  return "en-US";
}

const char* language_label(Language language) {
  switch (language) {
    case Language::EnUs:
      return "English";
    case Language::EsEs:
      return "Spanish";
    case Language::FrFr:
      return "French";
  }
  return "English";
}

Language language_from_index(std::size_t index) {
  switch (index % 3U) {
    case 0:
      return Language::EnUs;
    case 1:
      return Language::EsEs;
    case 2:
      return Language::FrFr;
  }
  return Language::EnUs;
}

std::size_t language_index(Language language) {
  switch (language) {
    case Language::EnUs:
      return 0;
    case Language::EsEs:
      return 1;
    case Language::FrFr:
      return 2;
  }
  return 0;
}

}  // namespace fridge_ink::app
