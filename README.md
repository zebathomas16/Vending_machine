# VENDORA — Version 13: Purchase history

Adds purchase history implemented with a bounded dynamically allocated FIFO linked list.

## Files

- `Vendora.ino` — stand-alone ESP32 firmware for this milestone.
- `vendora_gui.py` — standalone desktop GUI for this milestone.

## Run

Arduino IDE → ESP32 Dev Module → upload the `.ino` sketch. Close Arduino Serial Monitor before connecting a GUI.

Run `python vendora_gui.py` in V09–V13, or `python vendora_multiuser_gui.py` in V14.
Install pyserial with `python -m pip install pyserial`.

## Practical notes

- Versions 01–13 are **reconstructed teaching milestones**, NOT historical snapshots recovered from an actual Git repository.
- GPIO 16 and 17 are labeled RX2 and TX2 on the pictured 30-pin ESP32.
- Use an external regulated 5 V supply for each ULN2003 driver with common ground to ESP32.
- GPIO 2, 5, and 12 are boot-strapping pins; avoid pulling them to conflicting levels during reset.
- Power-off before changing wiring. A 5 V I2C LCD may require a bidirectional I2C level shifter.
- The linked list history exists only in RAM, and is not yet per-user. Persistence and individual accounts arrive in V14.
