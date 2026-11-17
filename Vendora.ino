/**
 * @file Vendora.ino
 * @brief VENDORA incremental milestone. ESP32-WROOM Dev Module.
 * All motor drivers require an external regulated 5V supply and shared ground.
 */
#include <Arduino.h>
#include <string.h>
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
void handleKey(char key) {
  if (key != '\0') { Serial.print("KEY,"); Serial.println(key); }
}
void setup() {
  Serial.begin(115200);
  initKeypad();
  Serial.println("VENDORA ESP32 READY");
}
void loop() {
  handleKey(readKeypad());
}
