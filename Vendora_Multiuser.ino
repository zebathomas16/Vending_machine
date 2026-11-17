/**
 * VENDORA - ESP32 two-item, multi-user smart vending machine.
 * Hardware: classic 30-pin ESP32 Dev Module, 4x4 keypad, 16x2 I2C LCD,
 *           2 x 28BYJ-48 + ULN2003 drivers.
 * Libraries: ESP32 Arduino core, hd44780 by Bill Perry.
 *
 * USB protocol: commands and replies are line-delimited CSV, 115200 baud.
 * Money is virtual (integer INR). This is a classroom prototype.
 */
#include <Arduino.h>
#include <Wire.h>
#include <Preferences.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
#include <new>
#include <time.h>
#include <sys/time.h>

constexpr uint8_t SDA_PIN = 21, SCL_PIN = 22;
constexpr uint8_t ROW_PINS[4] = {32, 33, 25, 26};
constexpr uint8_t COL_PINS[4] = {27, 14, 12, 13};
const char KEYMAP[4][4] = {
  {'1','2','3','A'}, {'4','5','6','B'},
  {'7','8','9','C'}, {'*','0','#','D'}
};
constexpr uint32_t LOCK_MS = 30000;
constexpr uint8_t MAX_FAILURES = 3;
constexpr uint8_t HISTORY_LIMIT = 24;
constexpr int32_t MAX_WALLET = 100000;

struct Product { uint8_t id; const char* name; int32_t price; int32_t stock; };
struct Account { char id[5]; char pin[5]; int32_t balance; };
struct MotorConfig { uint8_t pins[4]; int32_t steps; uint16_t delayUs; };
struct PurchaseRecord {
  uint32_t sequence;
  char userId[5];
  uint8_t item;
  int32_t price;
  int32_t balanceBefore;
  int32_t balanceAfter;
  uint32_t timestamp;
  uint32_t motorTimeUs;
};

// Four distinct user ID/PIN pairs for the college demonstration.
Account accounts[4] = {
  {"1001", "1234", 100}, {"1002", "5678", 100},
  {"1003", "2468", 100}, {"1004", "1357", 100}
};
Product products[2] = { {1, "ITEM 1", 20, 5}, {2, "ITEM 2", 30, 5} };
const MotorConfig MOTOR1 = {{16, 17, 18, 19}, 4096, 1500};
const MotorConfig MOTOR2 = {{23, 5, 4, 2}, 4096, 1500};

hd44780_I2Cexp lcd;
Preferences preferences;

// --------------------------------------------------
// LCD - displays 16 characters on each of two lines.
// --------------------------------------------------
class Display {
public:
  bool begin() {
    Wire.begin(SDA_PIN, SCL_PIN);
    Wire.setClock(100000);
    int result = lcd.begin(16, 2);
    if (result != 0) {
      Serial.print("ERROR,LCD_INIT,"); Serial.println(result);
      return false;
    }
    lcd.backlight();
    return true;
  }
  void show(const String& top, const String& bottom) {
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print(top.substring(0, 16));
    lcd.setCursor(0, 1); lcd.print(bottom.substring(0, 16));
  }
  void append(char c) { lcd.print(c); }
};

// --------------------------------------------------
// Keypad: non-blocking single-key edge detection.
// --------------------------------------------------
class MatrixKeypad {
  char previous = '\0';
  bool delivered = false;
  uint32_t changedAt = 0;
  char scan() {
    for (uint8_t r = 0; r < 4; ++r) pinMode(ROW_PINS[r], INPUT);
    for (uint8_t r = 0; r < 4; ++r) {
      digitalWrite(ROW_PINS[r], LOW);
      pinMode(ROW_PINS[r], OUTPUT);
      delayMicroseconds(40);
      for (uint8_t c = 0; c < 4; ++c) {
        if (digitalRead(COL_PINS[c]) == LOW) {
          pinMode(ROW_PINS[r], INPUT);
          return KEYMAP[r][c];
        }
      }
      pinMode(ROW_PINS[r], INPUT);
    }
    return '\0';
  }
public:
  void begin() {
    for (uint8_t r = 0; r < 4; ++r) pinMode(ROW_PINS[r], INPUT);
    for (uint8_t c = 0; c < 4; ++c) pinMode(COL_PINS[c], INPUT_PULLUP);
  }
  char read() {
    const char nowKey = scan();
    const uint32_t now = millis();
    if (nowKey != previous) {
      previous = nowKey; changedAt = now; delivered = false;
      return '\0';
    }
    if (nowKey == '\0' || delivered || now - changedAt < 30) return '\0';
    delivered = true;
    return nowKey;
  }
};

// --------------------------------------------------
// Motor interface + two motor objects (OOP polymorphism).
// --------------------------------------------------
class MotorDevice {
public:
  virtual void begin() = 0;
  virtual uint32_t run() = 0;
  virtual void release() = 0;
  virtual ~MotorDevice() {}
};

class Stepper28BYJ : public MotorDevice {
  MotorConfig config;
  static constexpr uint8_t HALF_STEPS[8][4] = {
    {1,0,0,0}, {1,1,0,0}, {0,1,0,0}, {0,1,1,0},
    {0,0,1,0}, {0,0,1,1}, {0,0,0,1}, {1,0,0,1}
  };
public:
  explicit Stepper28BYJ(const MotorConfig& c) : config(c) {}
  void begin() override {
    for (uint8_t p : config.pins) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  }
  void release() override {
    for (uint8_t p : config.pins) digitalWrite(p, LOW);
  }
  uint32_t run() override {
    uint32_t start = micros();
    for (int32_t s = 0; s < config.steps; ++s) {
      uint8_t phase = s & 7;
      for (uint8_t i = 0; i < 4; ++i)
        digitalWrite(config.pins[i], HALF_STEPS[phase][i]);
      delayMicroseconds(config.delayUs);
    }
    release();
    return micros() - start;
  }
};
constexpr uint8_t Stepper28BYJ::HALF_STEPS[8][4];

// --------------------------------------------------
// Bounded FIFO linked-list cache of saved transactions.
// Demonstrates pointers, dynamic nodes and a queue.
// Purchases are ALSO saved in ESP32 nonvolatile storage.
// --------------------------------------------------
struct TransactionNode {
  PurchaseRecord value;
  TransactionNode* next;
};

class TransactionQueue {
  TransactionNode* first = nullptr;
  TransactionNode* last = nullptr;
  uint8_t count = 0;
public:
  ~TransactionQueue() { while (first) removeOldest(); }
  void removeOldest() {
    if (!first) return;
    TransactionNode* old = first;
    first = first->next;
    if (!first) last = nullptr;
    delete old;
    --count;
  }
  bool add(const PurchaseRecord& record) {
    TransactionNode* node = new (std::nothrow) TransactionNode{record, nullptr};
    if (!node) return false;
    if (count == HISTORY_LIMIT) removeOldest();
    if (last) last->next = node;
    else first = node;
    last = node;
    ++count;
    return true;
  }
  void sendFor(const char* userId) const {
    for (TransactionNode* node = first; node; node = node->next) {
      const PurchaseRecord& record = node->value;
      if (strcmp(userId, record.userId) != 0) continue;
      Serial.print("HISTORY,"); Serial.print(record.userId);
      Serial.print(','); Serial.print(record.sequence);
      Serial.print(','); Serial.print(record.item);
      Serial.print(','); Serial.print(record.price);
      Serial.print(','); Serial.print(record.balanceBefore);
      Serial.print(','); Serial.print(record.balanceAfter);
      Serial.print(','); Serial.print(record.timestamp);
      Serial.print(','); Serial.println(record.motorTimeUs);
    }
  }
};

// --------------------------------------------------
// Vending controller: ESP32 owns authentication,
// wallets, stock and transaction history.
// --------------------------------------------------
class VendingMachine {
  Display screen;
  MatrixKeypad keypad;
  Stepper28BYJ motorOne{MOTOR1};
  Stepper28BYJ motorTwo{MOTOR2};
  int8_t active = -1;
  bool busy = false;
  uint8_t failures = 0;
  uint32_t lockStarted = 0;
  bool lockActive = false;
  uint32_t lastLockRefresh = 0;
  bool enteringPin = false;
  String keypadId, keypadPin;
  String inputLine;
  bool inputOverflow = false;
  uint8_t historyHead = 0, historyCount = 0;
  uint32_t transactionSequence = 0;
  TransactionQueue recentTransactions;

  static bool fourDigits(const String& value) {
    if (value.length() != 4) return false;
    for (uint8_t i = 0; i < 4; ++i)
      if (value[i] < '0' || value[i] > '9') return false;
    return true;
  }
  static bool amountFrom(const String& value, int32_t& amount) {
    if (value.length() == 0 || value.length() > 6) return false;
    for (unsigned i = 0; i < value.length(); ++i)
      if (value[i] < '0' || value[i] > '9') return false;
    amount = value.toInt();
    return amount > 0;
  }
  void emitStock() {
    Serial.print("STOCK,"); Serial.print(products[0].stock);
    Serial.print(','); Serial.print(products[1].stock);
    Serial.print(','); Serial.print(products[0].price);
    Serial.print(','); Serial.println(products[1].price);
  }
  void emitStatus() {
    if (lockActive) {
      uint32_t elapsed = millis() - lockStarted;
      uint32_t left = elapsed >= LOCK_MS ? 0 : (LOCK_MS - elapsed + 999) / 1000;
      Serial.print("LOCK,ACTIVE,"); Serial.println(left);
      return;
    }
    if (active < 0) {
      Serial.println("SESSION,NONE");
      return;
    }
    Serial.print("SESSION,"); Serial.println(accounts[active].id);
    Serial.print("WALLET,"); Serial.print(accounts[active].id);
    Serial.print(','); Serial.println(accounts[active].balance);
    emitStock();
  }
  // Notify the desktop GUI about the live keypad entry stage.
  // A passcode is NEVER sent over serial from keypad input.
  void startIdEntry() {
    enteringPin = false;
    keypadId = ""; keypadPin = "";
    screen.show("ENTER USER ID", "ID: ");
    Serial.println("INPUT,STAGE,ID");
  }
  void showMenu() {
    if (active < 0) { startIdEntry(); return; }
    screen.show(String("USER ") + accounts[active].id, "1-ITEM1 2-ITEM2");
  }
  void logout() {
    if (lockActive) { emitStatus(); return; }
    if (active >= 0) {
      Serial.print("LOGOUT,"); Serial.println(accounts[active].id);
    }
    active = -1;
    startIdEntry();
    Serial.println("SESSION,NONE");
  }
  void refreshLock() {
    if (!lockActive) return;
    if (millis() - lockStarted >= LOCK_MS) {
      lockActive = false; failures = 0;
      Serial.println("LOCK,RELEASED");
      startIdEntry();
    } else if (millis() - lastLockRefresh >= 1000) {
      lastLockRefresh = millis();
      uint32_t remaining = (LOCK_MS - (millis() - lockStarted) + 999) / 1000;
      screen.show("SYSTEM LOCKED", String("WAIT ") + remaining + " SEC");
    }
  }
  int8_t findUser(const String& id) {
    for (int8_t i = 0; i < 4; ++i)
      if (id == accounts[i].id) return i;
    return -1;
  }
  void login(const String& id, const String& pin) {
    if (lockActive) { emitStatus(); return; }
    if (busy) { Serial.println("ERROR,BUSY"); return; }
    if (active >= 0) { Serial.println("ERROR,SESSION_ACTIVE"); return; }
    if (!fourDigits(id) || !fourDigits(pin)) {
      Serial.println("ERROR,FOUR_DIGITS_REQUIRED"); return;
    }
    int8_t index = findUser(id);
    if (index >= 0 && pin == accounts[index].pin) {
      failures = 0;
      active = index;
      screen.show("ACCESS GRANTED", String("USER ") + id);
      Serial.print("AUTH,OK,"); Serial.println(id);
      emitStatus();
      delay(700);
      showMenu();
      return;
    }
    ++failures;
    Serial.print("AUTH,FAIL,"); Serial.println(MAX_FAILURES - failures);
    screen.show("INVALID ID / PIN", "TRY AGAIN");
    if (failures >= MAX_FAILURES) {
      lockActive = true; lockStarted = millis(); lastLockRefresh = millis();
      Serial.println("LOCK,ACTIVE,30");
      screen.show("SYSTEM LOCKED", "WAIT 30 SEC");
    } else {
      delay(700);
      startIdEntry();
    }
  }
  void sendHistory() {
    if (active < 0) { Serial.println("ERROR,LOGIN_REQUIRED"); return; }
    Serial.print("HISTORY_BEGIN,"); Serial.println(accounts[active].id);
    recentTransactions.sendFor(accounts[active].id);
    Serial.print("HISTORY_END,"); Serial.println(accounts[active].id);
  }
  void rememberPurchase(uint8_t item, int32_t price, int32_t before,
                        int32_t after, uint32_t timeUs) {
    PurchaseRecord record{};
    record.sequence = ++transactionSequence;
    strncpy(record.userId, accounts[active].id, sizeof(record.userId) - 1);
    record.item = item;
    record.price = price;
    record.balanceBefore = before;
    record.balanceAfter = after;
    time_t now = time(nullptr);
    // Time set by Python GUI; 0 means not synchronized yet.
    record.timestamp = now >= 1577836800 ? static_cast<uint32_t>(now) : 0;
    record.motorTimeUs = timeUs;
    if (!recentTransactions.add(record))
      Serial.println("ERROR,HISTORY_CACHE_FULL");
    uint8_t position = (historyHead + historyCount) % HISTORY_LIMIT;
    if (historyCount == HISTORY_LIMIT) {
      position = historyHead;
      historyHead = (historyHead + 1) % HISTORY_LIMIT;
    } else {
      ++historyCount;
    }
    String key = String("tx") + position;
    if (preferences.putBytes(key.c_str(), &record, sizeof(record)) != sizeof(record))
      Serial.println("ERROR,HISTORY_SAVE_FAILED");
    preferences.putUChar("txhead", historyHead);
    preferences.putUChar("txcount", historyCount);
    preferences.putUInt("txseq", transactionSequence);
  }
  void buy(uint8_t item) {
    if (lockActive || active < 0) { Serial.println("ERROR,LOGIN_REQUIRED"); return; }
    if (busy) { Serial.println("ERROR,BUSY"); return; }
    if (item != 1 && item != 2) { Serial.println("ERROR,INVALID_ITEM"); return; }
    Product& p = products[item - 1];
    Account& u = accounts[active];
    if (p.stock <= 0) {
      screen.show("OUT OF STOCK", "SELECT OTHER");
      Serial.print("ERROR,OUT_OF_STOCK,"); Serial.println(item);
      delay(800); showMenu(); return;
    }
    if (u.balance < p.price) {
      screen.show("LOW BALANCE", "RECHARGE WALLET");
      Serial.print("ERROR,LOW_BALANCE,"); Serial.println(item);
      delay(800); showMenu(); return;
    }
    busy = true;
    screen.show("DISPENSING...", String("ITEM ") + item);
    Serial.print("PURCHASE_START,"); Serial.print(u.id);
    Serial.print(','); Serial.println(item);
    MotorDevice* selected = (item == 1)
        ? static_cast<MotorDevice*>(&motorOne)
        : static_cast<MotorDevice*>(&motorTwo);
    uint32_t elapsed = selected->run();
    // Commanded motor cycle completed; no item-drop sensor is attached.
    int32_t before = u.balance;
    u.balance -= p.price;
    --p.stock;
    String balanceKey = String("bal") + active;
    String stockKey = String("stk") + (item - 1);
    bool walletSaved = preferences.putInt(balanceKey.c_str(), u.balance) == sizeof(int32_t);
    bool stockSaved = preferences.putInt(stockKey.c_str(), p.stock) == sizeof(int32_t);
    if (!walletSaved || !stockSaved) Serial.println("ERROR,PERSISTENCE_FAILED");
    rememberPurchase(item, p.price, before, u.balance, elapsed);
    Serial.print("PURCHASE_OK,"); Serial.print(u.id);
    Serial.print(','); Serial.print(item);
    Serial.print(','); Serial.print(p.price);
    Serial.print(','); Serial.print(before);
    Serial.print(','); Serial.print(u.balance);
    Serial.print(','); Serial.print(p.stock);
    Serial.print(','); Serial.println(elapsed);
    screen.show("ITEM DISPENSED", "THANK YOU!");
    busy = false;
    emitStatus();
    delay(900);
    showMenu();  // Keep same user logged in to view their account.
  }
  void recharge(int32_t amount) {
    if (lockActive || active < 0) { Serial.println("ERROR,LOGIN_REQUIRED"); return; }
    if (busy) { Serial.println("ERROR,BUSY"); return; }
    Account& u = accounts[active];
    if (amount < 1 || amount > 10000 || u.balance > MAX_WALLET - amount) {
      Serial.println("ERROR,INVALID_RECHARGE"); return;
    }
    int32_t before = u.balance;
    u.balance += amount;
    String key = String("bal") + active;
    if (preferences.putInt(key.c_str(), u.balance) != sizeof(int32_t))
      Serial.println("ERROR,PERSISTENCE_FAILED");
    Serial.print("RECHARGE_OK,"); Serial.print(u.id);
    Serial.print(','); Serial.print(amount);
    Serial.print(','); Serial.print(before);
    Serial.print(','); Serial.println(u.balance);
    screen.show("WALLET RECHARGED", String("BAL: RS ") + u.balance);
    emitStatus();
    delay(650);
    showMenu();
  }
  void command(String line) {
    line.trim();
    if (line == "STATUS") { emitStatus(); return; }
    if (line.startsWith("TIME,")) {
      String value = line.substring(5);
      // 10-digit Unix timestamp, coming from the host PC.
      if (value.length() != 10) { Serial.println("ERROR,BAD_TIME"); return; }
      for (unsigned i=0; i<value.length(); ++i)
        if (!isDigit(value[i])) { Serial.println("ERROR,BAD_TIME"); return; }
      uint32_t seconds = static_cast<uint32_t>(strtoul(value.c_str(), nullptr, 10));
      if (seconds < 1577836800) { Serial.println("ERROR,BAD_TIME"); return; }
      struct timeval tv{};
      tv.tv_sec = seconds;
      settimeofday(&tv, nullptr);
      Serial.println("TIME_OK");
      return;
    }
    if (line.startsWith("LOGIN,")) {
      int comma = line.indexOf(',', 6);
      if (comma < 0 || line.indexOf(',', comma + 1) >= 0) {
        Serial.println("ERROR,BAD_LOGIN_FORMAT"); return;
      }
      login(line.substring(6, comma), line.substring(comma + 1));
      return;
    }
    if (line == "LOGOUT") { logout(); return; }
    if (line == "HISTORY") { sendHistory(); return; }
    if (line.startsWith("BUY,")) {
      String item = line.substring(4);
      if (item == "1" || item == "2") buy(item.toInt());
      else Serial.println("ERROR,INVALID_ITEM");
      return;
    }
    if (line.startsWith("RECHARGE,")) {
      int32_t value = 0;
      if (!amountFrom(line.substring(9), value)) Serial.println("ERROR,INVALID_RECHARGE");
      else recharge(value);
      return;
    }
    Serial.println("ERROR,UNKNOWN_COMMAND");
  }
  void readSerial() {
    while (Serial.available()) {
      char ch = static_cast<char>(Serial.read());
      if (ch == '\n' || ch == '\r') {
        if (inputOverflow) Serial.println("ERROR,COMMAND_TOO_LONG");
        else if (inputLine.length()) command(inputLine);
        inputLine = "";
        inputOverflow = false;
      } else if (!inputOverflow) {
        if (inputLine.length() >= 79) {
          inputLine = ""; inputOverflow = true;
        } else inputLine += ch;
      }
    }
  }
  void handleKey(char key) {
    if (!key || busy || lockActive) return;
    if (key == '*') {
      if (active >= 0) logout();
      else startIdEntry();
      return;
    }
    if (active >= 0) {
      if (key == '1' || key == '2') buy(key - '0');
      return;
    }
    if (key >= '0' && key <= '9') {
      String& buffer = enteringPin ? keypadPin : keypadId;
      if (buffer.length() < 4) {
        buffer += key;
        screen.append(enteringPin ? '*' : key);
        // Mirror keypad data to GUI while preserving PIN confidentiality.
        // User ID is visible; PIN is always represented by asterisks.
        if (enteringPin) {
          Serial.print("INPUT,PIN,");
          for (unsigned i = 0; i < keypadPin.length(); ++i) Serial.print('*');
          Serial.println();
        } else {
          Serial.print("INPUT,ID,");
          Serial.println(keypadId);
        }
      }
    } else if (key == '#') {
      if (!enteringPin) {
        if (!fourDigits(keypadId)) {
          screen.show("INVALID USER ID", "ENTER 4 DIGITS");
          delay(500); startIdEntry();
        } else {
          enteringPin = true;
          keypadPin = "";
          screen.show("ENTER 4-DIGIT", "PIN: ");
          Serial.println("INPUT,STAGE,PIN");
        }
      } else {
        if (!fourDigits(keypadPin)) {
          screen.show("ENTER 4 DIGITS", "PIN REQUIRED");
          delay(500);
          keypadPin = "";
          screen.show("ENTER 4-DIGIT", "PIN: ");
          Serial.println("INPUT,PIN,");
          return;
        }
        String id = keypadId, pin = keypadPin;
        enteringPin = false; keypadId = ""; keypadPin = "";
        login(id, pin);
      }
    }
  }
public:
  void begin() {
    Serial.begin(115200);
    preferences.begin("vendora2", false);
    for (uint8_t i = 0; i < 4; ++i) {
      String key = String("bal") + i;
      accounts[i].balance = preferences.getInt(key.c_str(), 100);
      if (accounts[i].balance < 0 || accounts[i].balance > MAX_WALLET)
        accounts[i].balance = 100;
    }
    for (uint8_t i = 0; i < 2; ++i) {
      String key = String("stk") + i;
      products[i].stock = preferences.getInt(key.c_str(), 5);
      if (products[i].stock < 0 || products[i].stock > 1000) products[i].stock = 5;
    }
    historyHead = preferences.getUChar("txhead", 0);
    historyCount = preferences.getUChar("txcount", 0);
    transactionSequence = preferences.getUInt("txseq", 0);
    if (historyHead >= HISTORY_LIMIT) historyHead = 0;
    if (historyCount > HISTORY_LIMIT) historyCount = 0;
    for (uint8_t i = 0; i < historyCount; ++i) {
      uint8_t position = (historyHead + i) % HISTORY_LIMIT;
      String key = String("tx") + position;
      PurchaseRecord record{};
      if (preferences.getBytesLength(key.c_str()) == sizeof(record)) {
        preferences.getBytes(key.c_str(), &record, sizeof(record));
        if (!recentTransactions.add(record))
          Serial.println("ERROR,HISTORY_CACHE_FULL");
      }
    }
    keypad.begin();
    motorOne.begin(); motorTwo.begin();
    if (!screen.begin()) {
      Serial.println("ERROR,LCD_UNAVAILABLE");
      // Serial and motor functions can still be used without LCD.
    }
    startIdEntry();
    Serial.println("READY,VENDORA_MULTIUSER_V1");
    Serial.println("SESSION,NONE");
  }
  void update() {
    refreshLock();
    readSerial();
    handleKey(keypad.read());
  }
};

VendingMachine vending;
void setup() { vending.begin(); }
void loop() { vending.update(); }
