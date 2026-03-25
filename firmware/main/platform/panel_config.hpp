#pragma once

namespace fridge_ink::platform {

constexpr int kPanelWidth = 800;
constexpr int kPanelHeight = 480;
constexpr int kPanelWidthBytes = kPanelWidth / 8;
constexpr int kPanelBufferSize = kPanelWidthBytes * kPanelHeight;

}  // namespace fridge_ink::platform
