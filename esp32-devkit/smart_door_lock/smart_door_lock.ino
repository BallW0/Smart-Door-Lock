// ============================================================
// smart_door_lock.ino - ESP32 DevKit Smart Door Lock
// Auth 1: Face Recognition (via API polling)
// Auth 2: Keypad PIN (enter 4-digit PIN then #)
// ============================================================
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Keypad_I2C.h>
#include <Keypad.h>

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const String API_BASE_URL = "http://192.168.1.100:3000/api"; // UPDATE to Node.js IP

// PIN for second authentication (keypad)
const String DOOR_PIN = "1234"; // Change this to your desired PIN

unsigned long lastPollTime = 0;
const unsigned long POLL_INTERVAL = 2000; // Poll API every 2 seconds

unsigned long lastGrantTime = 0;
const unsigned long GRANT_COOLDOWN = 15000; // 15s cooldown after access granted

#define RELAY_PIN  21
#define BUZZER_PIN 15
#define LED_PIN    2

// Keypad I2C (PCF8574)
#define I2CADDR     0x20
#define I2C_SDA_PIN 33
#define I2C_SCL_PIN 32

const byte ROWS = 4;
const byte COLS = 4;
char keys[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};
byte rowPins[ROWS] = {0, 1, 2, 3}; // PCF8574 P0-P3
byte colPins[COLS] = {4, 5, 6, 7}; // PCF8574 P4-P7
Keypad_I2C keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS, I2CADDR);

// State Machine
enum SystemState {
  IDLE,       // Waiting for face recognition
  SECOND_AUTH // Face recognized, waiting for PIN
};
SystemState currentState = IDLE;
unsigned long secondAuthStartTime = 0;
const unsigned long SECOND_AUTH_TIMEOUT = 30000; // 30 seconds

String inputBuffer = "";

// ── Setup ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);

  digitalWrite(RELAY_PIN, HIGH); // Active LOW → HIGH = locked
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  // WiFi
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());

  // Init Keypad I2C
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  keypad.begin(makeKeymap(keys));

  Serial.println("System ready. Waiting for face recognition...");
}

// ── API: Poll for face_recognized flag ────────────────────────
void pollAPIForFace() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(API_BASE_URL + "/system/status");
  int httpCode = http.GET();

  if (httpCode == 200) {
    String res = http.getString();
    StaticJsonDocument<512> doc;
    deserializeJson(doc, res);

    if (doc["face_recognized"] == true) {
      Serial.println("[AUTH1] Face recognized! Enter PIN to unlock.");
      currentState = SECOND_AUTH;
      secondAuthStartTime = millis();
      inputBuffer = "";
      successBeep(); // 1 beep = face OK, waiting for PIN

      // Clear face_recognized flag so it doesn't trigger again
      HTTPClient clearHttp;
      clearHttp.begin(API_BASE_URL + "/system/clear-face-recognized");
      clearHttp.POST("");
      clearHttp.end();
    }
  }
  http.end();
}

// ── Main Loop ─────────────────────────────────────────────────
void loop() {
  // Poll API for face only when IDLE AND cooldown has passed after last grant
  if (currentState == IDLE
      && millis() - lastPollTime > POLL_INTERVAL
      && millis() - lastGrantTime > GRANT_COOLDOWN) {
    pollAPIForFace();
    lastPollTime = millis();
  }

  if (currentState == SECOND_AUTH) {
    digitalWrite(LED_PIN, HIGH); // LED on = waiting for PIN

    // Timeout: if no PIN entered within 30s, go back to IDLE
    if (millis() - secondAuthStartTime > SECOND_AUTH_TIMEOUT) {
      Serial.println("[AUTH2] Timeout. Returning to IDLE.");
      currentState = IDLE;
      inputBuffer = "";
      failBeep();
      digitalWrite(LED_PIN, LOW);
      logAccess("keypad", "denied", "Unknown", "2nd Auth Timeout");
      return;
    }

    // Read keypad for PIN input
    char key = keypad.getKey();
    if (key) {
      blinkLED();
      if (key == '#') {
        // Confirm PIN
        Serial.println("[AUTH2] PIN entered: " + inputBuffer);
        if (inputBuffer == DOOR_PIN) {
          grantAccess();
        } else {
          Serial.println("[AUTH2] Wrong PIN!");
          denyAccess("Wrong PIN");
        }
        inputBuffer = "";
      } else if (key == 'D') {
        // Clear input buffer
        inputBuffer = "";
        Serial.println("[AUTH2] Input cleared.");
      } else {
        inputBuffer += key;
        Serial.println("[AUTH2] Input: " + String(inputBuffer.length()) + " digits");
      }
    }
  }
  else if (currentState == IDLE) {
    digitalWrite(LED_PIN, LOW);
    // No keypad action in IDLE for door
    // (Keypad is only active during SECOND_AUTH)
  }
}

// ── Grant Access ──────────────────────────────────────────────
void grantAccess() {
  Serial.println("[GRANTED] Door unlocked!");
  // NOTE: state stays SECOND_AUTH during unlock to block re-entry from API poll
  digitalWrite(LED_PIN, LOW);

  successBeep();
  successBeep();
  digitalWrite(RELAY_PIN, LOW); // Unlock

  logAccess("keypad", "granted", "Authorized User", "PIN Correct - Door Unlocked");

  delay(5000); // Door open for 5 seconds
  digitalWrite(RELAY_PIN, HIGH); // Lock
  Serial.println("[SYSTEM] Door locked again.");

  lastGrantTime = millis(); // Start cooldown — blocks face poll for GRANT_COOLDOWN ms
  currentState = IDLE;      // Only go IDLE AFTER relay is locked

  // Update door_status back to 'locked' in Firebase
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(API_BASE_URL + "/system/door-status");
    http.addHeader("Content-Type", "application/json");
    http.POST("{\"status\":\"locked\"}");
    http.end();
  }
}

// ── Deny Access ───────────────────────────────────────────────
void denyAccess(String reason) {
  Serial.println("[DENIED] " + reason);
  currentState = IDLE;
  digitalWrite(LED_PIN, LOW);

  failBeep();
  logAccess("keypad", "denied", "Unknown", reason);
}

// ── Log to API ────────────────────────────────────────────────
void logAccess(String method, String status, String user, String details) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(API_BASE_URL + "/logs");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  doc["method"]  = method;
  doc["status"]  = status;
  doc["user"]    = user;
  doc["details"] = details;

  String payload;
  serializeJson(doc, payload);
  http.POST(payload);
  http.end();
}

// ── Helpers ───────────────────────────────────────────────────
void blinkLED() {
  digitalWrite(LED_PIN, LOW);
  delay(30);
  digitalWrite(LED_PIN, HIGH);
}

void successBeep() {
  tone(BUZZER_PIN, 1000, 150);
  delay(200);
}

void failBeep() {
  tone(BUZZER_PIN, 400, 800);
  delay(900);
}
