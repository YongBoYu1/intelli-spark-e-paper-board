idf_component_register(
    SRCS
        "main.cpp"
        "app/runtime.cpp"
        "app/state.cpp"
        "app/reducer.cpp"
        "app/defaults.cpp"
        "ui/render_app.cpp"
        "ui/screens/landing_screen.cpp"
        "ui/screens/home_screen.cpp"
        "platform/board_config.cpp"
        "platform/display.cpp"
        "platform/clock.cpp"
    INCLUDE_DIRS "."
)

target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
