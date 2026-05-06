#pragma once

#include "app/state.hpp"

// ── UI string table ────────────────────────────────────────────────────────────
// All strings are ASCII-only (the bitmap font only renders US-ASCII 32–126
// plus U+00B0 DEGREE SIGN at index 95).  Accented characters are romanised.
//
// Usage in a render function:
//   const auto& s = get_ui_strings(state.device_language);
//   draw_text_line(image, x, y, s.menu_title, …);

namespace fridge_ink::ui {

struct UiStrings {
  // ── Common ────────────────────────────────────────────────────────────────
  const char* on;
  const char* off;

  // ── Menu ─────────────────────────────────────────────────────────────────
  const char* menu_title;        // "MENU"
  const char* menu_memo;         // "MEMO" / "NOTA" / "NOTE"
  const char* menu_list;         // "LIST" / "LISTA" / "LISTE"
  const char* menu_timer;        // "TIMER" / "TEMPORIZADOR" / "MINUTEUR"
  const char* menu_calendar;     // "CALENDAR" / "CALENDARIO" / "CALENDRIER"
  const char* menu_settings;     // "SETTINGS" / "AJUSTES" / "PARAMETRES"
  const char* menu_hint;         // "Rotate to browse…"

  // ── Settings ─────────────────────────────────────────────────────────────
  const char* settings_title;
  const char* settings_hint_landscape;   // long rotate/click/hold hint
  const char* settings_hint_portrait;    // short rotate/click hint
  const char* settings_group_display;
  const char* settings_group_sync;
  const char* settings_group_other;
  const char* settings_font_size;
  const char* settings_partial_refresh;
  const char* settings_full_refresh;
  const char* settings_rotation;
  const char* settings_language;
  const char* settings_connectivity;
  const char* settings_auto_sync;
  const char* settings_sync_now;
  const char* settings_change_wifi;
  const char* settings_reset;
  const char* settings_press_enter;
  const char* settings_retry;
  const char* settings_click_again;
  const char* settings_not_set;
  const char* settings_syncing;          // "SYNCING..."
  const char* settings_every;            // "EVERY"   — landscape "EVERY N PARTIALS"
  const char* settings_partials;         // "PARTIALS"
  const char* settings_last_sync_prefix; // "LAST SYNC" (footer, then timestamp)
  const char* settings_last_sync_failed;
  const char* settings_last_sync_never;
  // portrait-only:
  const char* settings_sync_ok;
  const char* settings_sync_in_progress;
  const char* settings_sync_fail;
  const char* settings_sync_never;
  // font-size values:
  const char* settings_small;            // "SMALL"
  const char* settings_medium;           // "MEDIUM"
  const char* settings_large;            // "LARGE"
  // partial-refresh speed values:
  const char* settings_slow;             // "SLOW"
  const char* settings_balanced;         // "BALANCED"
  const char* settings_fast;             // "FAST"
  // time/sync status:
  const char* settings_never;            // "NEVER"
  const char* settings_invalid_time;     // "INVALID TIME"

  // ── Timer ─────────────────────────────────────────────────────────────────
  const char* timer_title;
  const char* timer_hint;        // "ROTATE=SELECT | CLICK=ENTER | HOLD=HOME"
  const char* timer_ready;
  const char* timer_running;
  const char* timer_paused;
  const char* timer_pause_btn;
  const char* timer_start_btn;
  const char* timer_reset_btn;
  const char* timer_1min_done;   // "1 MINUTE COUNTDOWN FINISHED"
  const char* timer_mins_done;   // " MINUTES COUNTDOWN FINISHED"

  // ── Memo ─────────────────────────────────────────────────────────────────
  const char* memo_title;
  const char* memo_hint;
  const char* memo_empty;
  const char* memo_empty_voice;
  const char* memo_badge_new;
  const char* memo_total;        // "TOTAL" (in summary line)
  const char* memo_count_new;    // "NEW"   (in summary line)
  const char* memo_focus;        // "FOCUS" (in summary line)
  const char* memo_showing;      // "SHOWING"
  const char* memo_of;           // "OF"
  const char* memo_footer;
  const char* memo_unknown;
  const char* memo_unknown_time;

  // ── List ─────────────────────────────────────────────────────────────────
  const char* list_title;
  const char* list_hint;
  const char* list_inventory;
  const char* list_reminder;
  const char* list_no_items;
  const char* list_done;
  const char* list_todo;
  const char* list_footer;

  // ── Calendar ─────────────────────────────────────────────────────────────
  const char* cal_sun;
  const char* cal_mon;
  const char* cal_tue;
  const char* cal_wed;
  const char* cal_thu;
  const char* cal_fri;
  const char* cal_sat;
  const char* cal_month_view;
  const char* cal_agenda;
  const char* cal_mode_agenda;
  const char* cal_mode_date;
  const char* cal_no_events;
  const char* cal_voice_hint;        // "Voice can add reminders and memos"
  const char* cal_voice_hint_upper;  // "VOICE CAN ADD REMINDERS AND MEMOS" (portrait)
  const char* cal_reminder;
  const char* cal_event;
  const char* cal_task;              // "TASK" (portrait detail)
  const char* cal_click_toggle;
  const char* cal_event_readonly;
  const char* cal_more;              // "MORE" (for "+N MORE")
  const char* cal_day;               // "DAY"  (for "DAY N")
  const char* cal_due_prefix;        // "DUE: " (portrait detail)

  // ── Weather (landscape — all caps) ────────────────────────────────────────
  const char* wx_feels_like;     // "FEELS LIKE" — prefixed to temperature
  const char* wx_feels_like_na;  // "FEELS LIKE --"
  const char* wx_syncing;        // "SYNCING..."
  const char* wx_humidity;       // "HUMIDITY"
  const char* wx_wind;           // "WIND"
  const char* wx_uv_index;       // "UV INDEX"

  // ── Weather (portrait — title case) ───────────────────────────────────────
  const char* wx_feels_like_lc;      // "Feels Like"
  const char* wx_no_weather_data;    // "No weather data"
  const char* wx_unknown_location;   // "Unknown" (shown when location is not yet set)
  const char* wx_syncing_lc;         // "Syncing..."
  const char* wx_waiting_sync;       // "Waiting for sync"
  const char* wx_waiting_wifi;       // "Waiting for WiFi"
  const char* wx_humidity_lc;        // "Humidity"
  const char* wx_wind_lc;            // "Wind"
  const char* wx_uv_index_lc;        // "UV Index"

  // ── Onboarding ────────────────────────────────────────────────────────────
  const char* ob_title;
  const char* ob_step_prefix;        // "STEP"
  const char* ob_configure_wifi;
  const char* ob_connect_wifi;
  const char* ob_select_wifi;
  const char* ob_skip_now;
  const char* ob_rotate_choose_press;
  const char* ob_select_network;
  const char* ob_press_rescan;
  const char* ob_rotate_scroll;
  const char* ob_skip;
  const char* ob_network;            // "NETWORK:"
  const char* ob_quick_prefs;
  const char* ob_change_later;
  const char* ob_language;
  const char* ob_timezone;
  const char* ob_auto_sync;
  const char* ob_timezone_prefix;    // "Timezone: "
  const char* ob_auto_sync_prefix;   // "Auto Sync: "
  const char* ob_wifi_prefix;        // "Wi-Fi: "
  const char* ob_language_prefix;    // "Language: "
  const char* ob_next_step;          // "NEXT STEP ->"
  const char* ob_voice_guide;        // "VOICE GUIDE >"
  const char* ob_hold_to_record;
  const char* ob_recording;
  const char* ob_example_cmds;
  const char* ob_ex_add_milk;
  const char* ob_ex_set_timer;
  const char* ob_ex_show_cal;
  const char* ob_result;
  const char* ob_no_result;
  const char* ob_hold_to_test;
  const char* ob_listening;
  const char* ob_press_skip;
  const char* ob_done_btn;           // "DONE >"
  const char* ob_skip_btn;           // "SKIP >"
  const char* ob_setup_complete;
  const char* ob_board_ready;
  const char* ob_enter_home;

  // ── Home screen ───────────────────────────────────────────────────────────
  const char* home_inventory;      // "INVENTORY"
  const char* home_reminders;      // "REMINDERS"
  const char* home_stocked;        // "STOCKED"
  const char* home_out;            // "OUT"
  const char* home_navigation;     // "NAVIGATION" (menu overlay header)
  const char* home_syncing;        // "SYNCING"    (compact, no ellipsis)
  const char* home_unsynced;       // "UNSYNCED"
  const char* home_hum_prefix;     // "HUM "       (weather humidity prefix)
  const char* home_hum_na;         // "HUM --"     (no humidity data)
  const char* home_hold_to_talk;   // "Hold to talk"

  // ── Landing ───────────────────────────────────────────────────────────────
  const char* land_subtitle;
  const char* land_tip_rotate;
  const char* land_tip_press;
  const char* land_tip_long;
  const char* land_tip_voice;
  const char* land_tip_move_focus;
  const char* land_tip_confirm;
  const char* land_tip_back_home;
  const char* land_tip_talk;
  const char* land_voice_unlock;
  const char* land_language;
  const char* land_status_done;
  const char* land_status_choose;
  const char* land_cta_home;
  const char* land_cta_rotate;
  const char* land_cta_click;

  // ── Detail scaffold ───────────────────────────────────────────────────────
  const char* scaffold_return_menu;   // "CLICK TO RETURN MENU"
};

// Returns a reference to the static string table for the given language.
const UiStrings& get_ui_strings(app::Language lang);

}  // namespace fridge_ink::ui
