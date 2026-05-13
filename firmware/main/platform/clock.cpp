#include "platform/clock.hpp"

#include "esp_timer.h"

#include <cstdlib>
#include <string>
#include <sys/time.h>

namespace fridge_ink::platform {

namespace {
constexpr std::time_t kValidWallClockThreshold = 1700000000;
std::string g_active_timezone_iana  = "UTC";
std::string g_active_timezone_posix = "UTC0";

// Canonical IANA name aliases — maps well-known variants to the primary entry
// kept in the POSIX table so that e.g. both "America/New_York" and
// "America/Toronto" resolve to the same DST rule.
std::string normalize_timezone_name(const std::string& zone_name) {
  if (zone_name.empty()) return "UTC";

  // ── North America aliases ─────────────────────────────────────────────
  if (zone_name == "America/New_York"              ||
      zone_name == "America/Indiana/Indianapolis"  ||
      zone_name == "America/Detroit")               return "America/Toronto";
  if (zone_name == "America/Winnipeg"              ||
      zone_name == "America/Indiana/Knox")          return "America/Chicago";
  if (zone_name == "America/Edmonton"              ||
      zone_name == "America/Boise")                 return "America/Denver";
  if (zone_name == "America/Vancouver")             return "America/Los_Angeles";
  if (zone_name == "America/Whitehorse")            return "America/Anchorage";
  if (zone_name == "America/Moncton")               return "America/Halifax";

  // ── Europe aliases ────────────────────────────────────────────────────
  if (zone_name == "Europe/Berlin"      ||
      zone_name == "Europe/Rome"        ||
      zone_name == "Europe/Madrid"      ||
      zone_name == "Europe/Amsterdam"   ||
      zone_name == "Europe/Brussels"    ||
      zone_name == "Europe/Vienna"      ||
      zone_name == "Europe/Warsaw"      ||
      zone_name == "Europe/Prague"      ||
      zone_name == "Europe/Stockholm"   ||
      zone_name == "Europe/Oslo"        ||
      zone_name == "Europe/Copenhagen") return "Europe/Paris";
  if (zone_name == "Europe/Athens"      ||
      zone_name == "Europe/Bucharest"   ||
      zone_name == "Europe/Sofia"       ||
      zone_name == "Europe/Tallinn"     ||
      zone_name == "Europe/Riga"        ||
      zone_name == "Europe/Vilnius"     ||
      zone_name == "Europe/Kiev"        ||
      zone_name == "Europe/Kyiv")       return "Europe/Helsinki";

  // ── Asia aliases ──────────────────────────────────────────────────────
  if (zone_name == "Asia/Chongqing"     ||
      zone_name == "Asia/Harbin"        ||
      zone_name == "Asia/Urumqi"        ||
      zone_name == "Asia/Taipei"        ||
      zone_name == "Asia/Macau"         ||
      zone_name == "Asia/Hong_Kong")    return "Asia/Shanghai";
  if (zone_name == "Asia/Calcutta")     return "Asia/Kolkata";
  if (zone_name == "Asia/Muscat"        ||
      zone_name == "Asia/Baku"          ||
      zone_name == "Asia/Tbilisi"       ||
      zone_name == "Asia/Yerevan")      return "Asia/Dubai";
  if (zone_name == "Asia/Phnom_Penh"   ||
      zone_name == "Asia/Vientiane"     ||
      zone_name == "Asia/Jakarta"       ||
      zone_name == "Asia/Pontianak")    return "Asia/Bangkok";   // UTC+7
  if (zone_name == "Asia/Brunei"        ||
      zone_name == "Asia/Kuala_Lumpur"  ||
      zone_name == "Asia/Makassar"      ||
      zone_name == "Asia/Ujung_Pandang")return "Asia/Singapore"; // UTC+8
  if (zone_name == "Asia/Katmandu")     return "Asia/Kathmandu";

  // ── Australia aliases ─────────────────────────────────────────────────
  if (zone_name == "Australia/Melbourne"||
      zone_name == "Australia/Hobart"   ||
      zone_name == "Australia/ACT"      ||
      zone_name == "Australia/Canberra")return "Australia/Sydney";

  // ── Pacific aliases ───────────────────────────────────────────────────
  if (zone_name == "Pacific/Chatham")   return "Pacific/Auckland"; // ~close

  // ── UTC variants ──────────────────────────────────────────────────────
  if (zone_name == "Etc/UTC" || zone_name == "Etc/GMT") return "UTC";

  return zone_name;
}

// Comprehensive IANA → POSIX TZ mapping.
// POSIX sign convention for UTC offset is inverted from IANA:
//   UTC+8 (east of UTC) → "CST-8"   ← negative POSIX offset
//   UTC-5 (west of UTC) → "EST5"    ← positive POSIX offset
// Returns empty string if the name is unknown (caller should use numeric fallback).
std::string iana_to_posix_tz(const std::string& zone_name) {
  const std::string z = normalize_timezone_name(zone_name);

  // ── North America ─────────────────────────────────────────────────────
  // DST rule: 2nd Sunday of March 02:00 → 1st Sunday of November 02:00
  if (z == "America/Toronto")      return "EST5EDT,M3.2.0/2,M11.1.0/2";
  if (z == "America/Chicago")      return "CST6CDT,M3.2.0/2,M11.1.0/2";
  if (z == "America/Denver")       return "MST7MDT,M3.2.0/2,M11.1.0/2";
  if (z == "America/Phoenix")      return "MST7";           // no DST
  if (z == "America/Los_Angeles")  return "PST8PDT,M3.2.0/2,M11.1.0/2";
  if (z == "America/Anchorage")    return "AKST9AKDT,M3.2.0/2,M11.1.0/2";
  if (z == "Pacific/Honolulu")     return "HST10";          // no DST
  if (z == "America/Halifax")      return "AST4ADT,M3.2.0/2,M11.1.0/2";
  if (z == "America/St_Johns")     return "NST3:30NDT,M3.2.0/0:01,M11.1.0/0:01";
  if (z == "America/Sao_Paulo")    return "<-03>3<-02>,M10.3.0/0,M2.3.0/0";
  if (z == "America/Argentina/Buenos_Aires") return "<-03>3";
  if (z == "America/Mexico_City")  return "CST6CDT,M4.1.0/2,M10.5.0/2";
  if (z == "America/Bogota"  ||
      z == "America/Lima"    ||
      z == "America/Guayaquil")    return "<-05>5";
  if (z == "America/Caracas")      return "<-04>4";

  // ── Europe ───────────────────────────────────────────────────────────
  // EU DST rule: last Sunday March 01:00 UTC → last Sunday October 01:00 UTC
  if (z == "Europe/London"   ||
      z == "Europe/Dublin"   ||
      z == "Europe/Lisbon")        return "GMT0BST,M3.5.0/1,M10.5.0";
  if (z == "Europe/Paris")         return "CET-1CEST,M3.5.0,M10.5.0/3";
  if (z == "Europe/Helsinki")      return "EET-2EEST,M3.5.0/3,M10.5.0/4";
  if (z == "Europe/Moscow"   ||
      z == "Europe/Istanbul" ||
      z == "Europe/Minsk")         return "MSK-3";          // no DST
  if (z == "Europe/Samara")        return "<+04>-4";
  if (z == "Europe/Yekaterinburg") return "<+05>-5";

  // ── Africa ────────────────────────────────────────────────────────────
  if (z == "Africa/Cairo")         return "EET-2";
  if (z == "Africa/Johannesburg"  ||
      z == "Africa/Harare")        return "SAST-2";
  if (z == "Africa/Nairobi")       return "EAT-3";
  if (z == "Africa/Lagos"    ||
      z == "Africa/Algiers")       return "WAT-1";

  // ── Middle East ───────────────────────────────────────────────────────
  if (z == "Asia/Dubai")           return "<+04>-4";
  if (z == "Asia/Tehran")          return "<+03:30>-3:30<+04:30>,80/0,264/0";
  if (z == "Asia/Jerusalem"  ||
      z == "Asia/Tel_Aviv")        return "IST-2IDT,M3.4.4/26,M10.5.0";
  if (z == "Asia/Riyadh"     ||
      z == "Asia/Baghdad"    ||
      z == "Asia/Kuwait")          return "<+03>-3";

  // ── South / Central Asia ──────────────────────────────────────────────
  if (z == "Asia/Karachi")         return "PKT-5";
  if (z == "Asia/Kolkata")         return "IST-5:30";
  if (z == "Asia/Colombo")         return "<+0530>-5:30";
  if (z == "Asia/Kathmandu")       return "<+0545>-5:45";
  if (z == "Asia/Dhaka")           return "<+06>-6";
  if (z == "Asia/Almaty")          return "<+06>-6";
  if (z == "Asia/Yangon"     ||
      z == "Asia/Rangoon")         return "<+0630>-6:30";

  // ── Southeast Asia ────────────────────────────────────────────────────
  if (z == "Asia/Bangkok")         return "<+07>-7";
  if (z == "Asia/Singapore")       return "<+08>-8";

  // ── East Asia ─────────────────────────────────────────────────────────
  if (z == "Asia/Shanghai")        return "CST-8";
  if (z == "Asia/Seoul")           return "KST-9";
  if (z == "Asia/Tokyo")           return "JST-9";

  // ── Australia / Pacific ───────────────────────────────────────────────
  // AU DST rule: 1st Sunday October 02:00 → 1st Sunday April 03:00
  if (z == "Australia/Perth")      return "AWST-8";
  if (z == "Australia/Brisbane")   return "AEST-10";        // no DST
  if (z == "Australia/Darwin")     return "ACST-9:30";      // no DST
  if (z == "Australia/Adelaide")   return "ACST-9:30ACDT,M10.1.0,M4.1.0/3";
  if (z == "Australia/Sydney")     return "AEST-10AEDT,M10.1.0,M4.1.0/3";
  if (z == "Pacific/Auckland")     return "NZST-12NZDT,M9.5.0,M4.1.0/3";
  if (z == "Pacific/Fiji")         return "<+12>-12";
  if (z == "Pacific/Guam"    ||
      z == "Pacific/Saipan")       return "ChST-10";

  // ── UTC ───────────────────────────────────────────────────────────────
  if (z == "UTC")                  return "UTC0";

  return {};  // unknown — caller should fall back to numeric UTC offset
}
}  // namespace

std::uint64_t monotonic_ms() {
  return static_cast<std::uint64_t>(esp_timer_get_time() / 1000ULL);
}

std::time_t wall_time_seconds() {
  return std::time(nullptr);
}

bool wall_time_is_valid() {
  return wall_time_seconds() >= kValidWallClockThreshold;
}

bool set_wall_time_seconds(const std::time_t unix_seconds) {
  if (unix_seconds < kValidWallClockThreshold) {
    return false;
  }
  timeval tv{};
  tv.tv_sec  = unix_seconds;
  tv.tv_usec = 0;
  return settimeofday(&tv, nullptr) == 0;
}

bool apply_timezone(const std::string& zone_name) {
  const std::string posix = iana_to_posix_tz(zone_name);
  if (posix.empty()) {
    // Zone not in table — let the caller (e.g. ntp_sync) use a numeric fallback.
    return false;
  }
  const std::string canonical = normalize_timezone_name(zone_name);
  if (canonical == g_active_timezone_iana && posix == g_active_timezone_posix) {
    return true;  // already set
  }
  if (setenv("TZ", posix.c_str(), 1) != 0) {
    return false;
  }
  tzset();
  g_active_timezone_iana  = canonical;
  g_active_timezone_posix = posix;
  return true;
}

const std::string& active_timezone_name() {
  return g_active_timezone_iana;
}

const std::string& active_posix_timezone() {
  return g_active_timezone_posix;
}

}  // namespace fridge_ink::platform
