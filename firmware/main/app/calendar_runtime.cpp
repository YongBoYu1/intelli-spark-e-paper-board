#include "app/calendar_runtime.hpp"

#include "platform/clock.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <ctime>
#include <optional>
#include <string>
#include <vector>

namespace fridge_ink::app::calendar_runtime {
namespace {

constexpr std::array<const char*, 12> kMonthNamesUpper = {
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"};

constexpr std::array<const char*, 7> kWeekdayNamesUpper = {
    "SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"};

constexpr std::array<const char*, 7> kWeekdayNamesUpperShort = {
    "SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};

struct WeekdayToken {
  const char* token;
  int index;
};

constexpr std::array<WeekdayToken, 17> kWeekdayTokens = {{
    {"mon", 1},
    {"monday", 1},
    {"tue", 2},
    {"tues", 2},
    {"tuesday", 2},
    {"wed", 3},
    {"wednesday", 3},
    {"thu", 4},
    {"thur", 4},
    {"thurs", 4},
    {"thursday", 4},
    {"fri", 5},
    {"friday", 5},
    {"sat", 6},
    {"saturday", 6},
    {"sun", 0},
    {"sunday", 0},
}};

bool same_date(const DateValue& lhs, const DateValue& rhs) {
  return lhs.year == rhs.year && lhs.month == rhs.month && lhs.day == rhs.day;
}

bool is_leap_year(const int year) {
  return ((year % 4) == 0 && (year % 100) != 0) || ((year % 400) == 0);
}

bool is_valid_date(const DateValue& date) {
  if (date.month < 1 || date.month > 12) {
    return false;
  }
  const int max_day = days_in_month(date.year, date.month);
  return date.day >= 1 && date.day <= max_day;
}

std::tm make_tm(const DateValue& date) {
  std::tm tm{};
  tm.tm_year = date.year - 1900;
  tm.tm_mon = date.month - 1;
  tm.tm_mday = date.day;
  tm.tm_hour = 12;
  tm.tm_min = 0;
  tm.tm_sec = 0;
  tm.tm_isdst = -1;
  return tm;
}

DateValue from_time_t_local(const std::time_t raw) {
  std::tm local_tm{};
#if defined(_WIN32)
  localtime_s(&local_tm, &raw);
#else
  localtime_r(&raw, &local_tm);
#endif
  return DateValue{
      1900 + local_tm.tm_year,
      local_tm.tm_mon + 1,
      local_tm.tm_mday,
  };
}

std::string trim_copy_ascii(const std::string& in) {
  std::size_t start = 0;
  while (start < in.size() && std::isspace(static_cast<unsigned char>(in[start]))) {
    ++start;
  }
  std::size_t end = in.size();
  while (end > start && std::isspace(static_cast<unsigned char>(in[end - 1]))) {
    --end;
  }
  return in.substr(start, end - start);
}

std::string normalize_token(const std::string& token) {
  std::string out;
  out.reserve(token.size());
  for (const char ch : token) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (std::isalpha(c)) {
      out.push_back(static_cast<char>(std::toupper(c)));
      continue;
    }
    if (std::isdigit(c)) {
      out.push_back(static_cast<char>(c));
    }
  }
  return out;
}

int parse_positive_int(const std::string& token, const int fallback) {
  if (token.empty()) {
    return fallback;
  }
  int value = 0;
  for (const char ch : token) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (!std::isdigit(c)) {
      return fallback;
    }
    value = (value * 10) + (ch - '0');
  }
  return value;
}

int month_from_token(const std::string& token) {
  const std::string normalized = normalize_token(token);
  for (std::size_t i = 0; i < kMonthNamesUpper.size(); ++i) {
    const std::string full = kMonthNamesUpper[i];
    const std::string short_name = full.substr(0, 3);
    if (normalized == full || normalized == short_name) {
      return static_cast<int>(i) + 1;
    }
  }
  return 0;
}

std::vector<std::string> split_words(const std::string& text) {
  std::vector<std::string> words;
  std::string current;
  for (const char ch : text) {
    const unsigned char c = static_cast<unsigned char>(ch);
    if (std::isalnum(c)) {
      current.push_back(ch);
      continue;
    }
    if (!current.empty()) {
      words.push_back(current);
      current.clear();
    }
  }
  if (!current.empty()) {
    words.push_back(current);
  }
  return words;
}

std::optional<DateValue> parse_iso_date(const std::string& text) {
  const std::string s = trim_copy_ascii(text);
  if (s.size() < 10) {
    return std::nullopt;
  }
  for (std::size_t i = 0; i + 9 < s.size(); ++i) {
    if (!std::isdigit(static_cast<unsigned char>(s[i])) ||
        !std::isdigit(static_cast<unsigned char>(s[i + 1])) ||
        !std::isdigit(static_cast<unsigned char>(s[i + 2])) ||
        !std::isdigit(static_cast<unsigned char>(s[i + 3])) ||
        s[i + 4] != '-' ||
        !std::isdigit(static_cast<unsigned char>(s[i + 5])) ||
        !std::isdigit(static_cast<unsigned char>(s[i + 6])) ||
        s[i + 7] != '-' ||
        !std::isdigit(static_cast<unsigned char>(s[i + 8])) ||
        !std::isdigit(static_cast<unsigned char>(s[i + 9]))) {
      continue;
    }
    const int year = ((s[i] - '0') * 1000) + ((s[i + 1] - '0') * 100) +
                     ((s[i + 2] - '0') * 10) + (s[i + 3] - '0');
    const int month = ((s[i + 5] - '0') * 10) + (s[i + 6] - '0');
    const int day = ((s[i + 8] - '0') * 10) + (s[i + 9] - '0');
    const DateValue parsed{year, month, day};
    if (is_valid_date(parsed)) {
      return parsed;
    }
  }
  return std::nullopt;
}

std::optional<DateValue> parse_month_day(
    const std::string& text,
    const int year) {
  const std::vector<std::string> words = split_words(trim_copy_ascii(text));
  if (words.size() < 2) {
    return std::nullopt;
  }
  int month = 0;
  int day = 0;
  for (std::size_t i = 0; i < words.size(); ++i) {
    month = month_from_token(words[i]);
    if (month <= 0) {
      continue;
    }
    for (std::size_t j = i + 1; j < words.size() && j <= i + 2; ++j) {
      const int parsed = parse_positive_int(words[j], -1);
      if (parsed > 0) {
        day = parsed;
        break;
      }
    }
    break;
  }
  if (month <= 0 || day <= 0) {
    return std::nullopt;
  }
  const DateValue parsed{year, month, day};
  if (!is_valid_date(parsed)) {
    return std::nullopt;
  }
  return parsed;
}

std::optional<DateValue> parse_weekday(
    const std::string& text,
    const DateValue& base) {
  const std::vector<std::string> words = split_words(trim_copy_ascii(text));
  if (words.empty()) {
    return std::nullopt;
  }
  int target_wday = -1;
  for (const auto& word : words) {
    const std::string lowered = [&]() {
      std::string out;
      out.reserve(word.size());
      for (const char ch : word) {
        out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
      }
      return out;
    }();
    for (const auto& token : kWeekdayTokens) {
      if (lowered == token.token) {
        target_wday = token.index;
        break;
      }
    }
    if (target_wday >= 0) {
      break;
    }
  }
  if (target_wday < 0) {
    return std::nullopt;
  }
  const int base_wday = weekday_sunday0(base);
  int delta = (target_wday - base_wday) % 7;
  if (delta < 0) {
    delta += 7;
  }
  return add_days(base, delta);
}

std::optional<DateValue> resolve_date_from_candidates(
    const std::vector<std::string>& candidates,
    const DateValue& base) {
  for (const auto& value : candidates) {
    const auto parsed = parse_iso_date(value);
    if (parsed.has_value()) {
      return parsed;
    }
  }
  for (const auto& value : candidates) {
    const auto parsed = parse_month_day(value, base.year);
    if (parsed.has_value()) {
      return parsed;
    }
  }
  for (const auto& value : candidates) {
    const auto parsed = parse_weekday(value, base);
    if (parsed.has_value()) {
      return parsed;
    }
  }
  return std::nullopt;
}

std::uint64_t fnv1a_seed() {
  return 1469598103934665603ULL;
}

void fnv1a_update_bytes(std::uint64_t& h, const void* data, const std::size_t len) {
  const auto* ptr = static_cast<const std::uint8_t*>(data);
  for (std::size_t i = 0; i < len; ++i) {
    h ^= static_cast<std::uint64_t>(ptr[i]);
    h *= 1099511628211ULL;
  }
}

void hash_string(std::uint64_t& h, const std::string& value) {
  fnv1a_update_bytes(h, value.data(), value.size());
  const std::uint8_t sep = 0xFF;
  fnv1a_update_bytes(h, &sep, sizeof(sep));
}

void hash_int(std::uint64_t& h, const int value) {
  fnv1a_update_bytes(h, &value, sizeof(value));
}

void hash_bool(std::uint64_t& h, const bool value) {
  const std::uint8_t raw = value ? 1U : 0U;
  fnv1a_update_bytes(h, &raw, sizeof(raw));
}

std::string month_title_case(const int month) {
  const char* upper = month_name_upper(month);
  std::string out = upper != nullptr ? std::string(upper) : std::string("MONTH");
  for (std::size_t i = 0; i < out.size(); ++i) {
    out[i] = static_cast<char>(i == 0
                                   ? std::toupper(static_cast<unsigned char>(out[i]))
                                   : std::tolower(static_cast<unsigned char>(out[i])));
  }
  return out;
}

std::string normalized_mode(const std::string& raw) {
  std::string out;
  out.reserve(raw.size());
  for (const char ch : raw) {
    out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
  }
  return out == "agenda" ? "agenda" : "date";
}

}  // namespace

DateValue today_local_date(const AppState& state) {
  if (platform::wall_time_is_valid()) {
    return from_time_t_local(platform::wall_time_seconds());
  }
  if (state.home.clock_minute_bucket > 0) {
    const std::time_t fallback_wall = static_cast<std::time_t>(
        state.home.clock_minute_bucket * 60ULL);
    return from_time_t_local(fallback_wall);
  }
  return from_time_t_local(std::time(nullptr));
}

DateValue add_days(const DateValue& base, const int delta_days) {
  std::tm tm = make_tm(base);
  tm.tm_mday += delta_days;
  const std::time_t shifted = std::mktime(&tm);
  return from_time_t_local(shifted);
}

DateValue cursor_date(const AppState& state, const DateValue& base) {
  return add_days(base, state.calendar.offset_days);
}

int days_in_month(const int year, const int month) {
  static constexpr std::array<int, 12> kDays = {
      31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  const int clamped_month = std::clamp(month, 1, 12);
  if (clamped_month == 2 && is_leap_year(year)) {
    return 29;
  }
  return kDays[static_cast<std::size_t>(clamped_month - 1)];
}

int weekday_sunday0(const DateValue& date) {
  std::tm tm = make_tm(date);
  if (std::mktime(&tm) == static_cast<std::time_t>(-1)) {
    return 0;
  }
  return std::clamp(tm.tm_wday, 0, 6);
}

const char* month_name_upper(const int month) {
  const int clamped = std::clamp(month, 1, 12);
  return kMonthNamesUpper[static_cast<std::size_t>(clamped - 1)];
}

const char* weekday_name_upper(const int weekday) {
  const int clamped = std::clamp(weekday, 0, 6);
  return kWeekdayNamesUpper[static_cast<std::size_t>(clamped)];
}

const char* weekday_name_upper_short(const int weekday) {
  const int clamped = std::clamp(weekday, 0, 6);
  return kWeekdayNamesUpperShort[static_cast<std::size_t>(clamped)];
}

std::string month_label_for_date(const DateValue& date) {
  return month_title_case(date.month) + " " + std::to_string(date.year);
}

std::string date_title_for_date(const DateValue& date) {
  return std::string(month_name_upper(date.month)) + " " + std::to_string(date.day);
}

void sync_calendar_cursor_fields(AppState& state) {
  state.calendar.mode = normalized_mode(state.calendar.mode);
  if (state.calendar.selected_index < 0) {
    state.calendar.selected_index = 0;
  }
  const DateValue base = today_local_date(state);
  const DateValue cursor = cursor_date(state, base);
  state.calendar.day_of_month = cursor.day;
  state.calendar.month_label = month_label_for_date(cursor);
}

AgendaSelection agenda_selection_for_date(
    const AppState& state,
    const DateValue& target,
    const DateValue& base) {
  AgendaSelection out{};

  std::vector<int> unresolved_events{};
  unresolved_events.reserve(state.dashboard.calendar_events.size());
  for (int i = 0; i < static_cast<int>(state.dashboard.calendar_events.size()); ++i) {
    const auto& event = state.dashboard.calendar_events[static_cast<std::size_t>(i)];
    const auto resolved = resolve_date_from_candidates(
        {event.date_iso, event.when, event.title},
        base);
    if (!resolved.has_value()) {
      unresolved_events.push_back(i);
      continue;
    }
    if (same_date(resolved.value(), target)) {
      out.event_indices.push_back(i);
    }
  }
  if (same_date(target, base)) {
    out.event_indices.insert(
        out.event_indices.end(),
        unresolved_events.begin(),
        unresolved_events.end());
  }

  std::vector<int> unresolved_reminders{};
  unresolved_reminders.reserve(state.dashboard.reminder_items.size());
  for (int i = 0; i < static_cast<int>(state.dashboard.reminder_items.size()); ++i) {
    std::string date_iso{};
    std::string right{};
    if (i < static_cast<int>(state.dashboard.reminder_meta.size())) {
      const auto& meta = state.dashboard.reminder_meta[static_cast<std::size_t>(i)];
      date_iso = meta.date_iso;
      right = meta.right;
    }
    const std::string& title = state.dashboard.reminder_items[static_cast<std::size_t>(i)];
    const auto resolved = resolve_date_from_candidates({date_iso, right, title}, base);
    if (!resolved.has_value()) {
      unresolved_reminders.push_back(i);
      continue;
    }
    if (same_date(resolved.value(), target)) {
      out.reminder_indices.push_back(i);
    }
  }
  if (same_date(target, base)) {
    out.reminder_indices.insert(
        out.reminder_indices.end(),
        unresolved_reminders.begin(),
        unresolved_reminders.end());
  }

  return out;
}

AgendaSelection agenda_selection_for_cursor(
    const AppState& state,
    const DateValue& base) {
  const DateValue target = cursor_date(state, base);
  return agenda_selection_for_date(state, target, base);
}

std::uint64_t calendar_events_digest(const AppState& state) {
  std::uint64_t h = fnv1a_seed();
  hash_int(h, static_cast<int>(state.dashboard.calendar_events.size()));
  for (const auto& event : state.dashboard.calendar_events) {
    hash_string(h, event.eid);
    hash_string(h, event.title);
    hash_string(h, event.when);
    hash_string(h, event.date_iso);
  }
  return h;
}

std::uint64_t reminders_calendar_digest(const AppState& state) {
  std::uint64_t h = fnv1a_seed();
  hash_int(h, static_cast<int>(state.dashboard.reminder_items.size()));
  hash_int(h, static_cast<int>(state.dashboard.reminder_completed.size()));
  hash_int(h, static_cast<int>(state.dashboard.reminder_meta.size()));

  const int reminder_count = static_cast<int>(state.dashboard.reminder_items.size());
  for (int i = 0; i < reminder_count; ++i) {
    hash_string(h, state.dashboard.reminder_items[static_cast<std::size_t>(i)]);
    const bool completed =
        i < static_cast<int>(state.dashboard.reminder_completed.size()) &&
        state.dashboard.reminder_completed[static_cast<std::size_t>(i)];
    hash_bool(h, completed);
    if (i < static_cast<int>(state.dashboard.reminder_meta.size())) {
      const auto& meta = state.dashboard.reminder_meta[static_cast<std::size_t>(i)];
      hash_string(h, meta.rid);
      hash_string(h, meta.right);
      hash_string(h, meta.date_iso);
    } else {
      hash_string(h, "");
      hash_string(h, "");
      hash_string(h, "");
    }
  }
  return h;
}

}  // namespace fridge_ink::app::calendar_runtime
