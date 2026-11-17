/**
 * @file Vendora.ino
 * @brief VENDORA incremental milestone. ESP32-WROOM Dev Module.
 * All motor drivers require an external regulated 5V supply and shared ground.
 */
#include <Arduino.h>
#include <string.h>
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
hd44780_I2Cexp lcd;
bool lcdReady = false;
void screen(const String& first, const String& second) {
  if (!lcdReady) return;
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print(first.substring(0, 16));
  lcd.setCursor(0, 1); lcd.print(second.substring(0, 16));
}
// Four by four physical matrix keypad; manually scanned (no Keypad library).
const uint8_t ROW_PINS[4] = {32, 33, 25, 26};
const uint8_t COL_PINS[4] = {27, 14, 12, 13};
const char KEYMAP[4][4] = {
  {'1','2','3','A'}, {'4','5','6','B'},
  {'7','8','9','C'}, {'*','0','#','D'}
};
char previousKey = '\0';
unsigned long keyChangedAt = 0;
bool keyDelivered = false;
void initKeypad() {
  for (uint8_t r=0; r<4; ++r) pinMode(ROW_PINS[r], INPUT);
  for (uint8_t c=0; c<4; ++c) pinMode(COL_PINS[c], INPUT_PULLUP);
}
char scanKeypad() {
  for (uint8_t r=0; r<4; ++r) pinMode(ROW_PINS[r], INPUT);
  for (uint8_t r=0; r<4; ++r) {
    digitalWrite(ROW_PINS[r], LOW);
    pinMode(ROW_PINS[r], OUTPUT);
    delayMicroseconds(40);
    for (uint8_t c=0; c<4; ++c) {
      if (digitalRead(COL_PINS[c]) == LOW) {
        pinMode(ROW_PINS[r], INPUT);
        return KEYMAP[r][c];
      }
    }
    pinMode(ROW_PINS[r], INPUT);
  }
  return '\0';
}
char readKeypad() {
  char key = scanKeypad();
  unsigned long now = millis();
  if (key != previousKey) {
    previousKey = key; keyChangedAt = now; keyDelivered = false;
    return '\0';
  }
  if (key == '\0' || keyDelivered || now-keyChangedAt < 30) return '\0';
  keyDelivered = true;
  return key;
}
// Four demonstration PINs only (not production-ready authentication).
const char* validPins[] = {"1234", "5678", "2468", "1357"};
String enteredPin;
bool authenticated = false;
bool pinMatches(const String& pin) {
  if (pin.length()!=4) return false;
  for (uint8_t i=0; i<4; ++i) if (pin == validPins[i]) return true;
  return false;
}
// Motor 1 uses RX2/TX2 (GPIO 16/17) and GPIO 18/19.
const uint8_t M1[4] = {16,17,18,19};
// 28BYJ-48 with ULN2003: eight correct half-step phases.
const uint8_t HALF_STEPS[8][4] = {
 {1,0,0,0}, {1,1,0,0}, {0,1,0,0}, {0,1,1,0},
 {0,0,1,0}, {0,0,1,1}, {0,0,0,1}, {1,0,0,1}
};
constexpr int MOTOR_STEPS = 4096; // Calibrate for the cardboard dispenser.
constexpr int STEP_DELAY_US = 1500;
void initMotor(const uint8_t pins[4]) {
  for (uint8_t i=0; i<4; ++i) {
    pinMode(pins[i], OUTPUT);
    digitalWrite(pins[i], LOW);
  }
}
void runMotor(const uint8_t pins[4]) {
  for (int s=0; s<MOTOR_STEPS; ++s) {
    uint8_t phase = s % 8;
    for (uint8_t i=0; i<4; ++i) digitalWrite(pins[i], HALF_STEPS[phase][i]);
    delayMicroseconds(STEP_DELAY_US);
  }
  for (uint8_t i=0; i<4; ++i) digitalWrite(pins[i], LOW);
}
// Motor 2 uses GPIO 23,5,4,2 (some are ESP32 boot-strap pins).
const uint8_t M2[4] = {23,5,4,2};
constexpr unsigned long LOCK_MS = 30000UL;
int wrongAttempts = 0;
bool securityLocked = false;
unsigned long lockStarted = 0;
unsigned long lockLCDUpdated = 0;
void updateSecurityLock() {
  if (!securityLocked) return;
  unsigned long elapsed = millis() - lockStarted;
  if (elapsed >= LOCK_MS) {
    securityLocked = false;
    wrongAttempts = 0;
    enteredPin = "";
    Serial.println("LOCK,RELEASED");
    screen("ENTER 4-DIGIT", "PIN: ");
  } else if (millis()-lockLCDUpdated >= 1000) {
    lockLCDUpdated = millis();
    screen("SYSTEM LOCKED", String("WAIT ") + (LOCK_MS-elapsed+999)/1000 + " SEC");
  }
}
// Simulated single-user wallet (multi-user wallets are introduced at v14).
int walletBalance = 100;
const int ITEM_PRICES[2] = {20,30};
void showEntry() {
  enteredPin="";
  authenticated=false;
  Serial.println("ENTER FOUR DIGIT PIN; press # to submit, * to clear");
  screen("ENTER 4-DIGIT", "PIN: ");
}
void showProducts() {
  Serial.println("SELECT ITEM: 1 or 2 (press * to logout)");
  screen("SELECT ITEM", "1-ITEM1 2-ITEM2");
}
void emitStatus() {
  Serial.print("STATUS,AUTH,"); Serial.println(authenticated ? 1 : 0);
  Serial.print("WALLET,"); Serial.println(walletBalance);
  Serial.print("PRICES,"); Serial.print(ITEM_PRICES[0]); Serial.print(","); Serial.println(ITEM_PRICES[1]);
}
void dispense(int item) {
  if (!authenticated) { Serial.println("ERROR,LOGIN_REQUIRED"); return; }
  if (item != 1 && item != 2) { Serial.println("ERROR,INVALID_ITEM"); return; }
  int price=ITEM_PRICES[item-1];
  if (walletBalance < price) { Serial.println("ERROR,LOW_BALANCE"); return; }
  screen("DISPENSING...", String("ITEM ") + item);
  Serial.print("MOTOR_START,"); Serial.println(item);
  unsigned long beginTime=micros();
  runMotor(item == 1 ? M1 : M2);
  unsigned long motorTime=micros()-beginTime;
  Serial.print("MOTOR_DONE,"); Serial.println(item);
  Serial.print("MOTOR_TIME_US,"); Serial.println(motorTime);
  walletBalance -= price;
  Serial.print("WALLET,"); Serial.println(walletBalance);
  screen("ITEM DISPENSED", "THANK YOU!");
  delay(700);
  showEntry();
  emitStatus();
}
void submitPIN() {
  if (enteredPin.length()!=4) { Serial.println("ERROR,PIN_NEEDS_4_DIGITS"); return; }
  if (pinMatches(enteredPin)) {
    authenticated=true;
    Serial.println("AUTH,OK");
    wrongAttempts = 0;
    screen("PIN VERIFIED", "ACCESS GRANTED");
    delay(700); showProducts();
    emitStatus();
  } else {
    Serial.println("AUTH,FAIL");
    ++wrongAttempts;
    if (wrongAttempts >= 3) {
      securityLocked = true; lockStarted=millis(); lockLCDUpdated=millis();
      Serial.println("LOCK,ACTIVE,30");
      screen("SYSTEM LOCKED", "WAIT 30 SEC");
    } else {
      screen("INVALID PIN", "TRY AGAIN");
      delay(800); showEntry();
    }
  }
}
void handleKey(char key) {
  if (key == '\0') return;
  if (securityLocked) return;
  if (key == '*') { showEntry(); return; }
  if (authenticated) {
    if (key == '1') dispense(1);
    else if (key == '2') dispense(2);
    return;
  }
  if (key >= '0' && key <= '9' && enteredPin.length()<4) {
    enteredPin += key;
    if (lcdReady) lcd.print('*');
    if (enteredPin.length()==4) Serial.println("PIN: ****");
  } else if (key == '#') submitPIN();
}
String commandBuffer;
void handleCommand(String cmd) {
  cmd.trim(); cmd.toUpperCase();
  if (cmd == "STATUS") { emitStatus(); return; }
  if (cmd == "LOGOUT") { showEntry(); emitStatus(); return; }
  if (cmd.startsWith("LOGIN,")) {
    if (authenticated) { Serial.println("ERROR,SESSION_ACTIVE"); return; }
    enteredPin=cmd.substring(6);
    submitPIN(); return;
  }
  if (cmd.startsWith("BUY,")) {
    String item=cmd.substring(4);
    if (item != "1" && item != "2") { Serial.println("ERROR,INVALID_ITEM"); return; }
    dispense(item.toInt()); return;
  }
  if (cmd.startsWith("RECHARGE,")) {
    if (!authenticated) { Serial.println("ERROR,LOGIN_REQUIRED"); return; }
    String value=cmd.substring(9);
    for (unsigned int i=0; i<value.length(); ++i)
      if (value[i]<'0' || value[i]>'9') { Serial.println("ERROR,INVALID_AMOUNT"); return; }
    if (!value.length() || value.length()>5) { Serial.println("ERROR,INVALID_AMOUNT"); return; }
    int amount=value.toInt();
    if (amount<1 || amount>10000 || walletBalance>100000-amount) {
      Serial.println("ERROR,INVALID_AMOUNT"); return;
    }
    walletBalance+=amount;
    Serial.print("RECHARGE_OK,"); Serial.print(amount); Serial.print(','); Serial.println(walletBalance);
    emitStatus(); return;
  }
  Serial.println("ERROR,UNKNOWN_COMMAND");
}
void readCommands() {
  while (Serial.available()) {
    char c=static_cast<char>(Serial.read());
    if (c=='\n' || c=='\r') {
      if (commandBuffer.length()) handleCommand(commandBuffer);
      commandBuffer="";
    } else if (commandBuffer.length() < 70) commandBuffer+=c;
    else { commandBuffer=""; Serial.println("ERROR,COMMAND_TOO_LONG"); }
  }
}
void setup() {
  Serial.begin(115200);
  initKeypad();
  Wire.begin(21,22);
  lcdReady=(lcd.begin(16,2)==0);
  if (lcdReady) lcd.backlight(); else Serial.println("LCD_NOT_DETECTED");
  initMotor(M1);
  initMotor(M2);
  Serial.println("VENDORA ESP32 READY");
  showEntry();
  emitStatus();
}
void loop() {
  updateSecurityLock();
  readCommands();
  handleKey(readKeypad());
}
