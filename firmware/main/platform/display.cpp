#include "platform/board_config.hpp"
#include "platform/display.hpp"

#include "esp_log.h"

#include <memory>

namespace fridge_ink::platform {
namespace {

constexpr const char* kTag = "display";

class SerialLoggingDisplay final : public Display {
 public:
  void init() override {
    const auto& board = default_board_config();
    ESP_LOGI(
        kTag,
        "Using serial display stub. Replace main/platform/display.cpp with the real e-paper driver.");
    ESP_LOGI(kTag, "Board target: %s", board.target);
    ESP_LOGI(kTag, "Board name: %s", board.board_name);
    ESP_LOGI(kTag, "Display: %s", board.display_name);
    ESP_LOGI(
        kTag,
        "Display pin map ready: %s",
        has_ready_display_pin_map(board) ? "yes" : "no");
  }

  void clear() override {}

  void present(const ScreenFrame& frame) override {
    ESP_LOGI(kTag, "----------------");
    if (!frame.title.empty()) {
      ESP_LOGI(kTag, "TITLE: %s", frame.title.c_str());
    }
    if (!frame.subtitle.empty()) {
      ESP_LOGI(kTag, "SUBTITLE: %s", frame.subtitle.c_str());
    }
    for (const auto& line : frame.body_lines) {
      ESP_LOGI(kTag, "BODY: %s", line.c_str());
    }
    if (!frame.footer.empty()) {
      ESP_LOGI(kTag, "FOOTER: %s", frame.footer.c_str());
    }
  }
};

}  // namespace

std::unique_ptr<Display> make_default_display() {
  return std::make_unique<SerialLoggingDisplay>();
}

}  // namespace fridge_ink::platform
