#pragma once

// Voice backend HTTP client.
//
// Wraps recorded PCM in a WAV container, base64-encodes it, and POSTs the
// payload to the /voice/interpret endpoint.  Requires WiFi to be connected
// before calling voice_interpret_pcm().
//
// Expected backend: backend/voice_api/app.py  (POST /voice/interpret)
// Request  JSON: { request_id, request_time, timezone, locale, audio_base64 }
// Response JSON: { request_id, actions: [{tool, args}] }

#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::platform {

struct VoiceClientConfig {
  // Full URL to the voice backend, e.g. "http://192.168.1.10:8000"
  const char* base_url{"http://localhost:8000"};
  // Optional Bearer token (set VOICE_API_TOKEN on the backend side).
  const char* auth_token{nullptr};
  const char* timezone{"UTC"};
  const char* locale{"en-US"};
  // HTTP request timeout in milliseconds.
  uint32_t timeout_ms{20000};
};

struct VoiceAction {
  std::string tool;       // e.g. "shopping_add_item"
  std::string args_json;  // raw JSON object string, e.g. {"item":"milk"}
};

struct VoiceResponse {
  bool ok{false};
  std::vector<VoiceAction> actions;
  std::string error;  // non-empty when !ok
};

// Send 16-bit PCM audio (16 kHz mono S16_LE) to the voice backend.
// Blocks until a response is received or the timeout expires.
// request_id should be a short unique string (e.g. "esp32-001").
VoiceResponse voice_interpret_pcm(const VoiceClientConfig& cfg,
                                  const std::vector<int16_t>& pcm,
                                  const char* request_id);

}  // namespace fridge_ink::platform
