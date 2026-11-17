# VENDORA — per-user ESP32 smart vending machine

This package contains **both** the revised ESP32 firmware and the Python desktop GUI. You MUST upload the new firmware for per-user wallets and ID/PIN verification; the old firmware used one shared wallet and does not understand the new login protocol.

## Included files

- `Vendora_Multiuser.ino` — ESP32 Arduino firmware
- `vendora_multiuser_gui.py` — professional desktop GUI (Tkinter, pyserial, qrcode)

## Demonstration user accounts

| User ID (4 digits) | PIN (4 digits) | Starting wallet |
| --- | --- | --- |
| 1001 | 1234 | ₹100 |
| 1002 | 5678 | ₹100 |
| 1003 | 2468 | ₹100 |
| 1004 | 1357 | ₹100 |

These are examples for a **college lab demonstration**, not secure production credentials. Replace them in the `accounts` array in the firmware if desired. Their balances are separate and saved in NVS. The same physical inventory is shared by all users, with initial stock 5 of each product, Item 1 ₹20 and Item 2 ₹30. After first run, values are stored in NVS and are not reset by merely uploading/restarting the sketch if the flash isn't erased. The new app uses namespace `vendora2` and starts a fresh set of balances/stock, separate from earlier sketches.

## Hardware (same as previous wiring)

| Device | ESP32 pins |
| --- | --- |
| I2C LCD SDA/SCL | GPIO 21/22 |
| Keypad rows | GPIO 32, 33, 25, 26 |
| Keypad columns | GPIO 27, 14, 12, 13 |
| ULN2003 driver 1 IN1..IN4 | GPIO 16 (RX2), 17 (TX2), 18, 19 |
| ULN2003 driver 2 IN1..IN4 | GPIO 23, 5, 4, 2 |

Connect each motor to its ULN2003 driver board. Use an external regulated 5V supply (preferably around 2A total for both motors) and connect both ULN2003 grounds and ESP32 GND to the same supply negative. Do not power motors from GPIO or ESP32 3.3V. Watch boot-strapping pins GPIO 2, 5, and 12: peripheral circuits must not hold these at incorrect levels when restarting. 5V LCD backpacks may require bidirectional I2C level shifters for the ESP32's 3.3V logic.

## Upload ESP32 firmware

1. Arduino IDE: board **ESP32 Dev Module**, port for your board (previously COM9).
2. Install `hd44780` by Bill Perry from Library Manager. `Wire` and `Preferences` are in the ESP32 Arduino core.
3. Open `Vendora_Multiuser.ino` in a folder named `Vendora_Multiuser` and upload.
4. If uploading fails, disconnect the motor drivers, set upload speed to 115200, upload, then reconnect with power off.
5. Close the Arduino Serial Monitor before opening Python GUI; only one program can usually own the COM port at a time.

## Run the GUI

```sh
python -m pip install pyserial "qrcode[pil]"
python vendora_multiuser_gui.py
```

Select the COM port and click **Connect**. Type the **4-digit User ID** and **4-digit masked PIN** on the GUI and click **Sign in**. The dashboard is hidden until the ESP32 itself confirms that credential pair. It then shows only that user's wallet and recent purchase history. Shared item stock is visible to authenticated users. To log in as another user, press **Log out** first.

## Live keypad echo (NEW)

Connect the ESP32 to the Python GUI on its USB COM port. On the physical 4×4 keypad:

1. Enter **four user-ID digits**: each digit appears immediately on the LCD and in the GUI **LIVE PHYSICAL KEYPAD** User ID field.
2. Press `#`: the LCD and GUI switch to passcode entry.
3. Enter **four PIN digits**: both displays show `****`, not the actual passcode digits.
4. Press `#`: ESP32 validates credentials; on success the GUI opens the authenticated user's *personal dashboard* automatically.
5. `*` clears current login entry or logs out (same behavior as original firmware). Lockout after 3 invalid logins is unchanged.

Examples of the serial protocol are `INPUT,ID,1001`, `INPUT,STAGE,PIN`, and `INPUT,PIN,****`. The actual PIN is never transmitted to the GUI by the keypad-event mechanism. The optional GUI sign-in form still works by sending the entered credentials to the ESP32 for validation.

## GUI screens and controls

- Login-only screen before authentication, with masked PIN entry.
- Personal dashboard after ESP32 confirmation: user's account ID, personal wallet, current stock of both items, individual OUT OF STOCK indication, purchase buttons, last purchase details, and **my purchase history**.
- Typed virtual recharge amount ₹1–₹10,000; a **demo QR**, then an explicit virtual-credit confirmation; wallet updates after ESP32's `RECHARGE_OK` reply. No money is transferred. User accounts can hold up to ₹100,000 virtual credit.
- After purchase, wallet is deducted only after the commanded stepper motor sequence finishes; individual balance/stock/history update in the GUI. The user remains logged in until logout, unlike the old auto-reset-per-purchase sketch.
- After three consecutive invalid credential attempts, ESP32 locks sign-in for 30 seconds. The GUI waits for firmware to release the lock.
- Keypad is still functional: **ID + #, then PIN + #**; `*` clears or logs out. A keypad login is reflected live in the GUI and opens the matching personal account after ESP32 confirms the ID and PIN.

## USB protocol (115200 baud, each command ends with newline)

GUI → ESP32:

- `LOGIN,1001,1234` — user ID + PIN verification on device
- `LOGOUT`
- `STATUS`
- `HISTORY`
- `BUY,1` or `BUY,2` — only works for authenticated session
- `RECHARGE,100` — only works for authenticated session, **virtual credits**
- `TIME,1790000000` — sync device date/time from computer for history timestamps

ESP32 → GUI:

- `INPUT,STAGE,ID` / `INPUT,ID,1001` / `INPUT,STAGE,PIN` / `INPUT,PIN,****` (live physical keypad echo; PIN masked)
- `AUTH,OK,1001` or `AUTH,FAIL,2`
- `SESSION,1001` / `SESSION,NONE`
- `WALLET,1001,100`
- `STOCK,5,5,20,30` — item stock and price
- `PURCHASE_START,1001,1`
- `PURCHASE_OK,1001,1,20,100,80,4,6150000`
- `RECHARGE_OK,1001,100,80,180`
- `HISTORY_BEGIN,1001` / `HISTORY,1001,1,1,20,100,80,1790000000,6150000` / `HISTORY_END,1001`
- `LOCK,ACTIVE,30` / `LOCK,RELEASED`
- `ERROR,LOW_BALANCE,1`, `ERROR,OUT_OF_STOCK,2`, etc.

## Persistence and honest limitations

- Wallets, common stock, and the **latest 24 purchases across all accounts combined** are saved to ESP32 Preferences/NVS. The linked-list FIFO queue caches them in RAM for filtering by user ID. Records older than the latest 24 across all users are overwritten.
- The PC sends a Unix time update at connection; before time sync, transaction timestamps are stored as `0` and shown as "Not synced".
- No sensor verifies an item physically dropped. `PURCHASE_OK` means the motor **completed its commanded sequence**, not guaranteed product delivery. Use an IR sensor if you need physical confirmation.
- 4-digit PINs over an unencrypted USB serial connection and firmware-embedded PINs are suitable **only for a supervised lab demonstration**. Do not use for real money, unattended public deployment, or sensitive credentials.
- Motor steps remain 4096 half-steps at 1500 microseconds between steps. Calibrate for the cardboard dispensing mechanism, and do first tests without products.
- Preferences/NVS writes are not an atomic multi-key database transaction. If power is lost between wallet and stock writes, balances and stock could disagree; production deployments need a journaled transaction scheme.
- Hardware operation and firmware compilation under the actual ESP32 Arduino core were not tested here. The Python GUI passed compilation and headless interface tests; the C++ sketch passed a C++ syntax check with test header stubs. Verify on your ESP32 before presenting.

## Testing note

This firmware and GUI update has undergone static checks and simulated serial-message tests, not a complete hardware integration test. Close Arduino Serial Monitor before connecting the GUI.
