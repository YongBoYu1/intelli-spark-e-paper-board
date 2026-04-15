#pragma once

#include "app/state.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace fridge_ink::app::calendar_runtime {

struct DateValue {
  int year{1970};
  int month{1};
  int day{1};
};

struct AgendaSelection {
  std::vector<int> event_indices{};
  std::vector<int> reminder_indices{};
};

DateValue today_local_date(const AppState& state);
DateValue add_days(const DateValue& base, int delta_days);
DateValue cursor_date(const AppState& state, const DateValue& base);

int days_in_month(int year, int month);
int weekday_sunday0(const DateValue& date);

const char* month_name_upper(int month);
const char* weekday_name_upper(int weekday_sunday0);
const char* weekday_name_upper_short(int weekday_sunday0);

std::string month_label_for_date(const DateValue& date);
std::string date_title_for_date(const DateValue& date);

void sync_calendar_cursor_fields(AppState& state);

AgendaSelection agenda_selection_for_date(
    const AppState& state,
    const DateValue& target,
    const DateValue& base);
AgendaSelection agenda_selection_for_cursor(
    const AppState& state,
    const DateValue& base);

std::uint64_t calendar_events_digest(const AppState& state);
std::uint64_t reminders_calendar_digest(const AppState& state);

}  // namespace fridge_ink::app::calendar_runtime
