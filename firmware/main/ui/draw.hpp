#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::ui {

// ── Pixel operations ─────────────────────────────────────────────────────────

void set_black_pixel(std::vector<uint8_t>& image, int x, int y);
void clear_pixel(std::vector<uint8_t>& image, int x, int y);
void fill_black_rect(std::vector<uint8_t>& image, int x0, int y0, int x1, int y1);
void fill_white_rect(std::vector<uint8_t>& image, int x0, int y0, int x1, int y1);

// ── Rectangle drawing ────────────────────────────────────────────────────────

void draw_outline_rect(
    std::vector<uint8_t>& image, int x0, int y0, int x1, int y1, int thickness);

bool point_in_rounded_rect(int px, int py, int x0, int y0, int x1, int y1, int radius);

void fill_rounded_rect(
    std::vector<uint8_t>& image, int x0, int y0, int x1, int y1, int radius, bool black);

void draw_rounded_rect_outline(
    std::vector<uint8_t>& image, int x0, int y0, int x1, int y1, int radius, int thickness);

void draw_rounded_rect_stroke(
    std::vector<uint8_t>& image, int x0, int y0, int x1, int y1, int radius, int thickness);

// ── Font / glyph rendering ──────────────────────────────────────────────────

void draw_glyph(
    std::vector<uint8_t>& image, int x, int y, char ch, int scale, bool black = true);

void draw_text_line(
    std::vector<uint8_t>& image, int x, int y,
    const std::string& text, int scale, int max_chars);

void draw_text_line_inverted(
    std::vector<uint8_t>& image, int x, int y,
    const std::string& text, int scale, int max_chars);

void draw_text_centered(
    std::vector<uint8_t>& image, int x0, int x1, int y,
    const std::string& text, int scale, int max_chars);

void draw_text_centered_inverted(
    std::vector<uint8_t>& image, int x0, int x1, int y,
    const std::string& text, int scale, int max_chars);

void draw_text_wrapped(
    std::vector<uint8_t>& image, int x, int y, int width_px,
    const std::string& text, int scale, int max_lines);

void draw_text_wrapped_inverted(
    std::vector<uint8_t>& image, int x, int y, int width_px,
    const std::string& text, int scale, int max_lines);

// ── Text measurement / utilities ─────────────────────────────────────────────

int text_width_px(const std::string& text, int scale);
std::string truncate_text_px(const std::string& text, int scale, int max_width_px);
std::string trunc_text(const std::string& text, int max_chars);
std::string trim_copy(const std::string& in);
std::vector<std::string> wrap_words(const std::string& text, std::size_t max_chars);

}  // namespace fridge_ink::ui
