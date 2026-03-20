#include "app/runtime.hpp"
#include "app/events.hpp"
#include "platform/clock.hpp"
#include "platform/display.hpp"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"

namespace {

constexpr const char* kTag = "main";
constexpr TickType_t kRuntimeTick = pdMS_TO_TICKS(1000);

}  // namespace

extern "C" void app_main(void) {
  ESP_LOGI(kTag, "Booting Fridge Ink firmware runtime V0");

  auto display = fridge_ink::platform::make_default_display();
  fridge_ink::app::Runtime runtime(*display);
  runtime.boot();

  while (true) {
    vTaskDelay(kRuntimeTick);
    runtime.dispatch(
        fridge_ink::app::Event::Tick(fridge_ink::platform::monotonic_ms()));
  }
}
