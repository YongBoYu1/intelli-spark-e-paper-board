#pragma once

#include <string>
#include <vector>

namespace fridge_ink::ui {

std::string text_ellipsis(const std::string& text, int scale, int max_width_px);

std::string draw_text_ellipsis(
    std::vector<uint8_t>& image,
    int x,
    int y,
    int width_px,
    const std::string& text,
    int scale,
    bool inverted = false);

void draw_checkbox(
    std::vector<uint8_t>& image,
    int x,
    int y,
    bool checked,
    bool focused,
    int size = 14);

void draw_list_row(
    std::vector<uint8_t>& image,
    int x,
    int y,
    int width_px,
    int height_px,
    const std::string& text,
    bool checked,
    bool focused,
    int text_scale = 2);

void draw_icon(
    std::vector<uint8_t>& image,
    int x,
    int y,
    const std::string& icon_id,
    int size);

}  // namespace fridge_ink::ui

