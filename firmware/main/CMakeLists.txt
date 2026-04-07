idf_component_register(
    SRCS
        "main.cpp"
        "app/runtime.cpp"
        "app/refresh_policy.cpp"
        "app/state.cpp"
        "app/reducer.cpp"
        "app/defaults.cpp"
        "ui/draw.cpp"
        "ui/primitives.cpp"
        "ui/render_app.cpp"
        "ui/screens/landing_screen.cpp"
        "ui/screens/onboarding_screen.cpp"
        "ui/screens/home_screen.cpp"
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
        "platform/board_config.cpp"
        "platform/display.cpp"
        "platform/clock.cpp"
        # Voice / microphone / WiFi
        "platform/mic_driver.cpp"
        "platform/voice_client.cpp"
        "platform/wifi_driver.cpp"
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
        # Base64 encoding (mbedtls)
        mbedtls
        # Real-time clock for request timestamps
        esp_timer
        # WiFi + networking stack
        esp_wifi
        esp_netif
        esp_event
        nvs_flash
)

target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
