#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

#define FLASH_LED_PIN      4

WebServer server(80);
WiFiServer commandServer(81);

void commandTask(void *pvParameters) {
  commandServer.begin();
  while(true) {
    WiFiClient client = commandServer.available();
    if (client) {
      unsigned long startTime = millis();
      while (client.connected() && !client.available()) {
        if (millis() - startTime > 1000) break;
        vTaskDelay(10 / portTICK_PERIOD_MS);
      }
      
      if (client.available()) {
        String req = client.readStringUntil('\r');
        
        // Read the rest of the HTTP headers to avoid TCP reset on close
        while (client.connected()) {
          if (client.available()) {
            String line = client.readStringUntil('\n');
            if (line == "\r") break; // Empty line means end of headers
          } else {
            if (millis() - startTime > 2000) break;
            vTaskDelay(10 / portTICK_PERIOD_MS);
          }
        }

        if (req.indexOf("/face-detected") != -1) {
          digitalWrite(FLASH_LED_PIN, HIGH);
          
          Serial2.println("FACE_OK");
          Serial.println("Received face detection on port 81, sent FACE_OK via UART");
          
          client.println("HTTP/1.1 200 OK");
          client.println("Content-Type: application/json");
          client.println("Connection: close");
          client.println();
          client.println("{\"success\":true}");
          
          vTaskDelay(100 / portTICK_PERIOD_MS);
          digitalWrite(FLASH_LED_PIN, LOW);
        } else {
          client.println("HTTP/1.1 404 Not Found");
          client.println("Connection: close");
          client.println();
        }
      }
      vTaskDelay(10 / portTICK_PERIOD_MS); // Give client time to receive
      client.stop();
    }
    vTaskDelay(10 / portTICK_PERIOD_MS);
  }
}

void handleStream() {
  WiFiClient client = server.client();
  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
  server.sendContent(response);

  while (true) {
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      break;
    }
    
    String header = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + String(fb->len) + "\r\n\r\n";
    server.sendContent(header);
    client.write((const char *)fb->buf, fb->len);
    server.sendContent("\r\n");
    
    esp_camera_fb_return(fb);
    
    if (!client.connected()) break;
  }
}



void handleStatus() {
  String json = "{\"ip\":\"" + WiFi.localIP().toString() + "\", \"stream_url\":\"http://" + WiFi.localIP().toString() + "/stream\", \"uptime_seconds\":" + String(millis()/1000) + "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, 15, 14); // RX=15, TX=14 (Connect TX14 to RX34 on DevKit)
  
  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);
  
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  if(psramFound()){
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }
  
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }
  
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected");
  
  server.on("/stream", HTTP_GET, handleStream);
  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
  
  Serial.print("Camera Stream Ready! Go to: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/stream");
  
  // Start the background task for receiving commands on Core 0
  xTaskCreatePinnedToCore(commandTask, "CommandTask", 4096, NULL, 1, NULL, 0);
}

void loop() {
  server.handleClient();
}
