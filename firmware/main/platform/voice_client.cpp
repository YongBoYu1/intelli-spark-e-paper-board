#include "platform/voice_client.hpp"

#include "esp_http_client.h"
#include "esp_log.h"
#include "mbedtls/base64.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

namespace fridge_ink::platform {
namespace {

static const char* kTag = "voice_client";

// ── WAV header ────────────────────────────────────────────────────────────────

static constexpr uint32_t kSampleRate  = 16000;
static constexpr uint16_t kChannels    = 1;
static constexpr uint16_t kBitsPerSamp = 16;
static constexpr uint16_t kBlockAlign  = kChannels * (kBitsPerSamp / 8);
static constexpr uint32_t kByteRate    = kSampleRate * kBlockAlign;

// Write a 4-byte little-endian value into buf at offset.
static void write_le32(uint8_t* buf, size_t off, uint32_t v) {
  buf[off]     = static_cast<uint8_t>(v);
  buf[off + 1] = static_cast<uint8_t>(v >> 8);
  buf[off + 2] = static_cast<uint8_t>(v >> 16);
  buf[off + 3] = static_cast<uint8_t>(v >> 24);
}
static void write_le16(uint8_t* buf, size_t off, uint16_t v) {
  buf[off]     = static_cast<uint8_t>(v);
  buf[off + 1] = static_cast<uint8_t>(v >> 8);
}

// Build a canonical 44-byte PCM WAV header.
static void build_wav_header(uint8_t hdr[44], uint32_t pcm_bytes) {
  const uint32_t data_size  = pcm_bytes;
  const uint32_t riff_size  = 36 + data_size;

  memcpy(hdr,      "RIFF", 4);
  write_le32(hdr,  4, riff_size);
  memcpy(hdr + 8,  "WAVE", 4);
  memcpy(hdr + 12, "fmt ", 4);
  write_le32(hdr, 16, 16);               // fmt chunk size
  write_le16(hdr, 20, 1);               // PCM format
  write_le16(hdr, 22, kChannels);
  write_le32(hdr, 24, kSampleRate);
  write_le32(hdr, 28, kByteRate);
  write_le16(hdr, 32, kBlockAlign);
  write_le16(hdr, 34, kBitsPerSamp);
  memcpy(hdr + 36, "data", 4);
  write_le32(hdr, 40, data_size);
}

// ── Base64 helpers ────────────────────────────────────────────────────────────

// Returns the base64-encoded string of src.
static std::string base64_encode(const uint8_t* src, size_t src_len) {
  // mbedtls output length: 4 * ceil(n/3) + 1 (null terminator)
  const size_t out_len = ((src_len + 2) / 3) * 4 + 1;
  std::string out(out_len, '\0');
  size_t written = 0;
  const int rc = mbedtls_base64_encode(
      reinterpret_cast<unsigned char*>(&out[0]), out_len,
      &written, src, src_len);
  if (rc != 0) {
    ESP_LOGE(kTag, "mbedtls_base64_encode failed: %d", rc);
    return {};
  }
  out.resize(written);
  return out;
}

// ── ISO-8601 timestamp ────────────────────────────────────────────────────────

static std::string iso8601_now() {
  time_t now = 0;
  time(&now);
  struct tm tm_info {};
  gmtime_r(&now, &tm_info);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm_info);
  return buf;
}

// ── JSON helpers ──────────────────────────────────────────────────────────────

// Minimal JSON string escaping (control chars and quotes only).
static std::string json_str(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 2);
  out += '"';
  for (char c : s) {
    if (c == '"' || c == '\\') out += '\\';
    out += c;
  }
  out += '"';
  return out;
}

// Extract the string value of the first occurrence of "key":"value" in json.
// Returns empty string if not found.
static std::string extract_string(const std::string& json, const char* key) {
  const std::string needle = std::string("\"") + key + "\":\"";
  const size_t pos = json.find(needle);
  if (pos == std::string::npos) return {};
  const size_t start = pos + needle.size();
  const size_t end   = json.find('"', start);
  if (end == std::string::npos) return {};
  return json.substr(start, end - start);
}

// Extract all {"tool":"...","args":{...}} objects from the actions array.
static std::vector<VoiceAction> extract_actions(const std::string& json) {
  std::vector<VoiceAction> result;
  // Locate "actions":[
  const size_t arr_start = json.find("\"actions\":[");
  if (arr_start == std::string::npos) return result;

  size_t pos = arr_start + 11;  // skip "actions":[
  while (pos < json.size()) {
    // Find next '{' (start of an action object)
    pos = json.find('{', pos);
    if (pos == std::string::npos) break;

    // Find the matching '}' — simple brace counter (handles nested objects).
    int depth = 0;
    size_t obj_start = pos;
    size_t obj_end   = pos;
    for (size_t i = pos; i < json.size(); i++) {
      if (json[i] == '{') depth++;
      else if (json[i] == '}') {
        depth--;
        if (depth == 0) { obj_end = i; break; }
      }
    }
    if (obj_end <= obj_start) break;

    const std::string obj = json.substr(obj_start, obj_end - obj_start + 1);

    VoiceAction action;
    action.tool = extract_string(obj, "tool");

    // Extract raw args JSON object.
    const size_t args_pos = obj.find("\"args\":");
    if (args_pos != std::string::npos) {
      size_t args_start = obj.find('{', args_pos + 7);
      if (args_start != std::string::npos) {
        int d = 0;
        size_t args_end = args_start;
        for (size_t i = args_start; i < obj.size(); i++) {
          if (obj[i] == '{') d++;
          else if (obj[i] == '}') {
            d--;
            if (d == 0) { args_end = i; break; }
          }
        }
        action.args_json = obj.substr(args_start, args_end - args_start + 1);
      }
    }

    if (!action.tool.empty()) {
      result.push_back(std::move(action));
    }
    pos = obj_end + 1;
  }
  return result;
}

// ── HTTP client wrapper ───────────────────────────────────────────────────────

struct HttpResult {
  int    status{-1};
  std::string body;
};

static HttpResult http_post_json(const char* url,
                                 const char* auth_token,
                                 const std::string& body,
                                 uint32_t timeout_ms) {
  HttpResult result;

  esp_http_client_config_t cfg{};
  cfg.url            = url;
  cfg.method         = HTTP_METHOD_POST;
  cfg.timeout_ms     = static_cast<int>(timeout_ms);
  cfg.buffer_size    = 512;
  cfg.buffer_size_tx = 512;

  esp_http_client_handle_t client = esp_http_client_init(&cfg);
  if (!client) {
    ESP_LOGE(kTag, "esp_http_client_init failed");
    result.body = "esp_http_client_init failed";
    return result;
  }

  esp_http_client_set_header(client, "Content-Type", "application/json");
  if (auth_token && auth_token[0] != '\0') {
    const std::string bearer = std::string("Bearer ") + auth_token;
    esp_http_client_set_header(client, "Authorization", bearer.c_str());
  }

  esp_err_t err = esp_http_client_open(client, static_cast<int>(body.size()));
  if (err != ESP_OK) {
    ESP_LOGE(kTag, "esp_http_client_open: %s", esp_err_to_name(err));
    result.body = esp_err_to_name(err);
    esp_http_client_cleanup(client);
    return result;
  }

  // Write request body.
  const int written = esp_http_client_write(
      client, body.c_str(), static_cast<int>(body.size()));
  if (written < 0) {
    ESP_LOGE(kTag, "esp_http_client_write failed");
    result.body = "write failed";
    esp_http_client_cleanup(client);
    return result;
  }

  // Read response headers to get status + content-length.
  const int content_len = esp_http_client_fetch_headers(client);
  result.status = esp_http_client_get_status_code(client);
  ESP_LOGI(kTag, "HTTP %d  content-length=%d", result.status, content_len);

  // Read response body (cap at 8 KB to protect heap).
  constexpr int kMaxBody = 8192;
  const int buf_sz = (content_len > 0 && content_len < kMaxBody)
                         ? content_len + 1
                         : kMaxBody;
  result.body.resize(static_cast<size_t>(buf_sz), '\0');

  int total = 0;
  while (total < buf_sz - 1) {
    const int rd = esp_http_client_read(
        client, &result.body[total], buf_sz - 1 - total);
    if (rd <= 0) break;
    total += rd;
  }
  result.body.resize(static_cast<size_t>(total));

  esp_http_client_cleanup(client);
  return result;
}

}  // namespace

// ── Public API ────────────────────────────────────────────────────────────────

VoiceResponse voice_interpret_pcm(const VoiceClientConfig& cfg,
                                  const std::vector<int16_t>& pcm,
                                  const char* request_id) {
  VoiceResponse resp;

  if (pcm.empty()) {
    resp.error = "empty PCM buffer";
    ESP_LOGE(kTag, "%s", resp.error.c_str());
    return resp;
  }

  // 1. Build WAV bytes (header + PCM).
  const uint32_t pcm_bytes = static_cast<uint32_t>(pcm.size() * sizeof(int16_t));
  std::vector<uint8_t> wav(44 + pcm_bytes);
  build_wav_header(wav.data(), pcm_bytes);
  memcpy(wav.data() + 44, pcm.data(), pcm_bytes);

  ESP_LOGI(kTag, "WAV: %zu bytes  (%.2f s)",
           wav.size(), pcm.size() / static_cast<float>(kSampleRate));

  // 2. Base64-encode the WAV.
  const std::string b64 = base64_encode(wav.data(), wav.size());
  if (b64.empty()) {
    resp.error = "base64 encoding failed";
    return resp;
  }
  // Free WAV buffer immediately — we no longer need it.
  { std::vector<uint8_t> tmp; tmp.swap(wav); }

  // 3. Build JSON request body.
  const std::string ts = iso8601_now();
  std::string body;
  body.reserve(b64.size() + 256);
  body += '{';
  body += "\"request_id\":"   + json_str(request_id) + ',';
  body += "\"request_time\":" + json_str(ts) + ',';
  body += "\"timezone\":"     + json_str(cfg.timezone) + ',';
  body += "\"locale\":"       + json_str(cfg.locale) + ',';
  body += "\"audio_base64\":" + '"' + b64 + '"';
  body += '}';

  // Free b64 string immediately.
  { std::string tmp; tmp.swap(const_cast<std::string&>(b64)); }

  // 4. POST to backend.
  const std::string url = std::string(cfg.base_url) + "/voice/interpret";
  ESP_LOGI(kTag, "POST %s  body=%zu bytes", url.c_str(), body.size());

  const HttpResult http = http_post_json(
      url.c_str(), cfg.auth_token, body, cfg.timeout_ms);

  if (http.status != 200) {
    resp.error = "HTTP " + std::to_string(http.status) + ": " + http.body;
    ESP_LOGE(kTag, "Request failed: %s", resp.error.c_str());
    return resp;
  }

  // 5. Parse response.
  resp.actions = extract_actions(http.body);
  resp.ok = true;

  if (resp.actions.empty()) {
    ESP_LOGI(kTag, "Response OK — no actions returned");
  } else {
    for (const auto& a : resp.actions) {
      ESP_LOGI(kTag, "Action: tool=%s  args=%s",
               a.tool.c_str(), a.args_json.c_str());
    }
  }

  return resp;
}

}  // namespace fridge_ink::platform
