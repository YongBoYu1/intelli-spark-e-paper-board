idf_component_register(
    SRCS
        "main.cpp"
        "app/runtime.cpp"
        "app/refresh_policy.cpp"
        "app/state.cpp"
        "app/reducer.cpp"
        "app/defaults.cpp"
        "app/calendar_runtime.cpp"
        "ui/draw.cpp"
        "ui/primitives.cpp"
        "ui/render_app.cpp"
        "ui/strings.cpp"
        "ui/screens/landing_screen.cpp"
        "ui/screens/onboarding_screen.cpp"
        "ui/screens/home_screen.cpp"
        "ui/screens/home_screen_portrait.cpp"
        "ui/screens/menu_screen.cpp"
        "ui/screens/detail_screen_scaffold.cpp"
        "ui/screens/list_screen.cpp"
        "ui/screens/list_screen_landscape.cpp"
        "ui/screens/list_screen_portrait.cpp"
        "ui/screens/memo_screen.cpp"
        "ui/screens/memo_screen_landscape.cpp"
        "ui/screens/memo_screen_portrait.cpp"
        "ui/screens/timer_screen.cpp"
        "ui/screens/timer_screen_landscape.cpp"
        "ui/screens/timer_screen_portrait.cpp"
        "ui/screens/calendar_screen.cpp"
        "ui/screens/calendar_screen_landscape.cpp"
        "ui/screens/calendar_screen_portrait.cpp"
        "ui/screens/settings_screen.cpp"
        "ui/screens/settings_screen_landscape.cpp"
        "ui/screens/settings_screen_portrait.cpp"
        "ui/screens/placeholder_screen.cpp"
        "ui/screens/weather_screen.cpp"
        "ui/screens/weather_screen_landscape.cpp"
        "ui/screens/weather_screen_portrait.cpp"
        "platform/board_config.cpp"
        "platform/display.cpp"
        "platform/clock.cpp"
        "platform/live_data_provider.cpp"
        "platform/persistent_store.cpp"
        # Voice / microphone / WiFi
        "platform/encoder_driver.cpp"
        "platform/mic_driver.cpp"
        "platform/voice_client.cpp"
        "platform/wifi_driver.cpp"
        "platform/ntp_sync.cpp"
        "platform/weather_client.cpp"
    INCLUDE_DIRS "."
    EMBED_FILES
        "assets/landing_en.raw"
    PRIV_REQUIRES
        # esp_app_desc.h (used by app/defaults.cpp)
        esp_app_format
        # I2S microphone driver
        driver
        # HTTP client for voice backend
        esp_http_client
        # Base64 encoding + TLS certificate bundle (HTTPS for voice backend)
        mbedtls
        # Real-time clock for request timestamps
        esp_timer
        # WiFi + networking stack
        esp_wifi
        esp_netif
        esp_event
        nvs_flash
        # SNTP for NTP time sync
        lwip
)

target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
