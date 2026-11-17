# VENDORA — Version 04: Added 16x2 I2C LCD

Adds 16x2 I2C LCD display and masked PIN entry, same keypad/PIN behavior.

## Files

- `Vendora.ino` — stand-alone ESP32 firmware for this milestone.

## Run

Arduino IDE → ESP32 Dev Module → upload the `.ino` sketch. Close Arduino Serial Monitor before connecting a GUI.

## Practical notes

- Versions 01–13 are **reconstructed teaching milestones**, NOT historical snapshots recovered from an actual Git repository.
- GPIO 16 and 17 are labeled RX2 and TX2 on the pictured 30-pin ESP32.
- Use an external regulated 5 V supply for each ULN2003 driver with common ground to ESP32.
- GPIO 2, 5, and 12 are boot-strapping pins; avoid pulling them to conflicting levels during reset.
- Power-off before changing wiring. A 5 V I2C LCD may require a bidirectional I2C level shifter.
