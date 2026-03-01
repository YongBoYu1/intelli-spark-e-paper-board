# Rotary Encoder Wiring + Demo (Raspberry Pi 4B)

This guide targets the 5-pin rotary encoder module labeled:

- `GND`
- `S1`
- `S2`
- `KEY`
- `5V`

## 1) Wiring

Recommended default mapping in this repo:

| Encoder module pin | Raspberry Pi 4B pin (physical) | BCM GPIO |
| --- | --- | --- |
| `GND` | Pin 6 | GND |
| `5V` (module power pin) | Pin 1 | 3V3 |
| `S1` | Pin 36 | GPIO16 |
| `S2` | Pin 38 | GPIO20 |
| `KEY` | Pin 40 | GPIO21 |

Important:

- The module silkscreen says `5V`, but for Raspberry Pi GPIO safety, connect that pin to `3V3`.
- Power off Raspberry Pi before wiring.

## 2) Install dependency

```bash
sudo apt update
sudo apt install -y python3-rpi.gpio
```

## 3) Run demo

From repo root:

```bash
sudo python3 hardware_tests/test_rotary_encoder.py
```

Expected output:

- Rotate knob: `rotate CW` / `rotate CCW`
- Press knob: `key press`

Stop with `Ctrl+C`, then a summary is printed.

## 4) Use custom GPIO pins

If your default pins are occupied:

```bash
sudo python3 hardware_tests/test_rotary_encoder.py \
  --pin-s1 17 \
  --pin-s2 18 \
  --pin-key 27
```

Useful options:

- `--flip-direction` if clockwise/counterclockwise appears reversed.
- `--key-active high` if your button outputs high level when pressed.
- `--steps-per-detent 2` for encoders that report fewer transitions per notch.
- `--duration 20` to auto-stop after 20 seconds.

## 5) Troubleshooting

No events:

- Verify wiring and ground first.
- Confirm GPIO levels while rotating/pressing:

```bash
raspi-gpio get 16 20 21
```

Direction reversed:

- Swap `S1` and `S2`, or run with `--flip-direction`.

Too many duplicate key presses:

- Increase `--debounce-ms` (for example `--debounce-ms 250`).
