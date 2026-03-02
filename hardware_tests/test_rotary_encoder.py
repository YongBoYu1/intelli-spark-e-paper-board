#!/usr/bin/env python3
"""
Rotary encoder hardware test for Raspberry Pi.

Default wiring targets a 5-pin encoder module:
- GND -> Pi GND
- 5V  -> Pi 3V3 (important: keep GPIO at 3.3V)
- S1  -> GPIO16
- S2  -> GPIO20
- KEY -> GPIO21
"""

from __future__ import annotations

import argparse
import time

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None


CW_SEQ = {
    (0b00, 0b01),
    (0b01, 0b11),
    (0b11, 0b10),
    (0b10, 0b00),
}
CCW_SEQ = {
    (0b00, 0b10),
    (0b10, 0b11),
    (0b11, 0b01),
    (0b01, 0b00),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rotary encoder GPIO test")
    parser.add_argument("--pin-s1", type=int, default=16, help="BCM pin for S1 / CLK (default: 16)")
    parser.add_argument("--pin-s2", type=int, default=20, help="BCM pin for S2 / DT (default: 20)")
    parser.add_argument("--pin-key", type=int, default=21, help="BCM pin for KEY / SW (default: 21)")
    parser.add_argument("--pull", choices=["up", "down"], default="up", help="Internal pull resistor mode")
    parser.add_argument(
        "--key-active",
        choices=["low", "high"],
        default="low",
        help="Button active level (default: low)",
    )
    parser.add_argument("--steps-per-detent", type=int, default=4, help="Quadrature steps needed to emit one turn")
    parser.add_argument("--debounce-ms", type=int, default=180, help="Button debounce window")
    parser.add_argument("--poll-ms", type=float, default=1.0, help="Polling interval in milliseconds")
    parser.add_argument("--flip-direction", action="store_true", help="Swap clockwise/counterclockwise output")
    parser.add_argument("--duration", type=float, default=0.0, help="Exit after N seconds (0 means forever)")
    return parser.parse_args()


def _read_ab(pin_s1: int, pin_s2: int) -> int:
    return (GPIO.input(pin_s1) << 1) | GPIO.input(pin_s2)


def main() -> int:
    args = _parse_args()

    if GPIO is None:
        print("RPi.GPIO is not available. Install with: sudo apt install python3-rpi.gpio")
        return 1

    pull = GPIO.PUD_UP if args.pull == "up" else GPIO.PUD_DOWN
    poll_s = max(0.0005, args.poll_ms / 1000.0)
    steps_per_detent = max(1, int(args.steps_per_detent))
    debounce_s = max(0.0, args.debounce_ms / 1000.0)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.pin_s1, GPIO.IN, pull_up_down=pull)
    GPIO.setup(args.pin_s2, GPIO.IN, pull_up_down=pull)
    GPIO.setup(args.pin_key, GPIO.IN, pull_up_down=pull)

    prev_ab = _read_ab(args.pin_s1, args.pin_s2)
    prev_key = GPIO.input(args.pin_key)
    accum = 0
    cw_count = 0
    ccw_count = 0
    key_count = 0
    last_press_at = 0.0
    start = time.time()
    flip = bool(args.flip_direction)

    print("Rotary encoder test started.")
    print(
        f"Pins: S1={args.pin_s1}, S2={args.pin_s2}, KEY={args.pin_key}, "
        f"pull={args.pull}, key_active={args.key_active}, steps_per_detent={steps_per_detent}"
    )
    print("Press Ctrl+C to stop.")

    try:
        while True:
            now = time.time()
            if args.duration > 0 and (now - start) >= args.duration:
                break

            curr_ab = _read_ab(args.pin_s1, args.pin_s2)
            if curr_ab != prev_ab:
                edge = (prev_ab, curr_ab)
                if edge in CW_SEQ:
                    accum += 1
                elif edge in CCW_SEQ:
                    accum -= 1

                if accum >= steps_per_detent:
                    # Raw quadrature direction is CW; optionally flip to logical direction.
                    logical_cw = not flip
                    if logical_cw:
                        cw_count += 1
                        direction = "CW"
                    else:
                        ccw_count += 1
                        direction = "CCW"
                    print(f"{now:.3f} rotate {direction} (cw={cw_count}, ccw={ccw_count})")
                    accum = 0
                elif accum <= -steps_per_detent:
                    # Raw quadrature direction is CCW; optionally flip to logical direction.
                    logical_cw = flip
                    if logical_cw:
                        cw_count += 1
                        direction = "CW"
                    else:
                        ccw_count += 1
                        direction = "CCW"
                    print(f"{now:.3f} rotate {direction} (cw={cw_count}, ccw={ccw_count})")
                    accum = 0

                prev_ab = curr_ab

            curr_key = GPIO.input(args.pin_key)
            is_press_edge = (
                (args.key_active == "low" and prev_key == GPIO.HIGH and curr_key == GPIO.LOW)
                or (args.key_active == "high" and prev_key == GPIO.LOW and curr_key == GPIO.HIGH)
            )
            if is_press_edge:
                if now - last_press_at >= debounce_s:
                    key_count += 1
                    last_press_at = now
                    print(f"{now:.3f} key press (count={key_count})")
            prev_key = curr_key

            time.sleep(poll_s)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()

    elapsed = max(0.001, time.time() - start)
    print("Stopped.")
    print(
        "Summary: "
        f"cw={cw_count}, ccw={ccw_count}, key={key_count}, elapsed={elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
