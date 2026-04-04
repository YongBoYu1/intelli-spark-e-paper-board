#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {

std::vector<uint8_t> render_detail_scaffold_bitmap(
    const std::string& title,
    const std::string& line_one,
    const std::string& line_two,
    const std::string& line_three,
    const std::string& orientation_label);

}  // namespace fridge_ink::ui
