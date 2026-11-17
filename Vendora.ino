/** @file Vendora.ino @brief Version 01: ESP32 serial initialization. */
#include <Arduino.h>
unsigned long previousMessage = 0;
void setup() {
  Serial.begin(115200);
  Serial.println("VENDORA V01: ESP32 INITIALIZED");
}
void loop() {
  if (millis() - previousMessage >= 1000) {
    previousMessage = millis();
    Serial.println("ESP32 heartbeat OK");
  }
}
