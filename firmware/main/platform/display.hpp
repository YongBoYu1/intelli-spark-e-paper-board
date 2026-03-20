#pragma once

#include <memory>
#include <string>
#include <vector>

namespace fridge_ink::platform {

struct ScreenFrame {
  std::string title{};
  std::string subtitle{};
  std::vector<std::string> body_lines{};
  std::string footer{};
};

class Display {
 public:
  virtual ~Display() = default;

  virtual void init() = 0;
  virtual void clear() = 0;
  virtual void present(const ScreenFrame& frame) = 0;
};

std::unique_ptr<Display> make_default_display();

}  // namespace fridge_ink::platform
