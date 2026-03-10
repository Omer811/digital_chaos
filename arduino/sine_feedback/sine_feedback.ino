/*
  PWM feedback experiment with buffered sample transfer.

  Text protocol:
    SETUP,<pwm_pin>,<analog_pin>
    CAPS
    RUN,<count>,<settle_us>,<oversample_count>,<oversample_delay_us>

  Sequence for RUN:
    1) Host sends RUN line.
    2) Device replies: OK_RUN
    3) Host sends <count> raw PWM bytes.
    4) Device processes samples in-place and replies:
       DATA,<count>
       followed by <count> uint16 little-endian ADC averages.

  Replies:
    READY
    OK_SETUP
    CAPS,<max_buffer_samples>
    OK_RUN
    DATA,<count>
    ERROR,...
*/

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

extern unsigned int __heap_start;
extern void* __brkval;

const unsigned long BAUD_RATE = 115200;
const int MAX_LINE = 120;
const unsigned long IO_TIMEOUT_MS = 5000;
const int STACK_GUARD_BYTES = 384;
const int MIN_BUFFER_SAMPLES = 16;
const int MAX_BUFFER_SAMPLES_CAP = 900;

char lineBuffer[MAX_LINE];
int lineLength = 0;
int configuredPwmPin = 9;
int configuredAnalogPin = 0;
bool isConfigured = false;

uint8_t* pwmBuffer = NULL;
uint16_t* sampleBuffer = NULL;
uint16_t maxBufferSamples = 0;

int freeMemory() {
  int local;
  int heap = (__brkval == NULL) ? (int)&__heap_start : (int)__brkval;
  return (int)&local - heap;
}

uint16_t allocateLargestBuffer() {
  int freeBytes = freeMemory();
  int budget = freeBytes - STACK_GUARD_BYTES;
  int bytes_per_sample = (int)sizeof(uint16_t) + 1;
  if (budget < (MIN_BUFFER_SAMPLES * bytes_per_sample)) {
    return 0;
  }

  int target = budget / bytes_per_sample;
  if (target > MAX_BUFFER_SAMPLES_CAP) {
    target = MAX_BUFFER_SAMPLES_CAP;
  }

  for (int n = target; n >= MIN_BUFFER_SAMPLES; n -= 8) {
    pwmBuffer = (uint8_t*)malloc((size_t)n);
    if (pwmBuffer == NULL) {
      continue;
    }
    sampleBuffer = (uint16_t*)malloc((size_t)n * sizeof(uint16_t));
    if (sampleBuffer != NULL) {
      return (uint16_t)n;
    }
    free(pwmBuffer);
    pwmBuffer = NULL;
  }
  return 0;
}

bool readLine() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      lineBuffer[lineLength] = '\0';
      lineLength = 0;
      return true;
    }
    if (lineLength < (MAX_LINE - 1)) {
      lineBuffer[lineLength++] = c;
    }
  }
  return false;
}

bool readExactBytes(uint8_t* dst, unsigned int count, unsigned long timeoutMs) {
  unsigned int readCount = 0;
  unsigned long startMs = millis();
  while (readCount < count) {
    if (Serial.available() > 0) {
      dst[readCount++] = (uint8_t)Serial.read();
      startMs = millis();
      continue;
    }
    if ((millis() - startMs) > timeoutMs) {
      return false;
    }
  }
  return true;
}

bool parseSetupCommand(char* input, int* pwmPin, int* analogPin) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "SETUP") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *pwmPin = atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *analogPin = atoi(token);

  if (*pwmPin < 0 || *pwmPin > 13) return false;
  if (*analogPin < 0 || *analogPin > 5) return false;
  return true;
}

bool parseRunCommand(
  char* input,
  unsigned int* count,
  unsigned long* settleUs,
  unsigned int* oversampleCount,
  unsigned long* oversampleDelayUs
) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "RUN") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *count = (unsigned int)atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *settleUs = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *oversampleCount = (unsigned int)atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *oversampleDelayUs = strtoul(token, NULL, 10);

  if (*count < 1 || *count > maxBufferSamples) return false;
  if (*oversampleCount < 1 || *oversampleCount > 256) return false;
  return true;
}

uint16_t measureAvgAdc(unsigned long settleUs, unsigned int oversampleCount, unsigned long oversampleDelayUs) {
  if (settleUs > 0) {
    delayMicroseconds(settleUs);
  }

  unsigned long sum = 0;
  for (unsigned int i = 0; i < oversampleCount; i++) {
    int v = analogRead(A0 + configuredAnalogPin);
    sum += (unsigned long)v;
    if (oversampleDelayUs > 0 && i + 1 < oversampleCount) {
      delayMicroseconds(oversampleDelayUs);
    }
  }
  return (uint16_t)(sum / (unsigned long)oversampleCount);
}

void runBuffered(
  unsigned int count,
  unsigned long settleUs,
  unsigned int oversampleCount,
  unsigned long oversampleDelayUs
) {
  Serial.println("OK_RUN");

  if (!readExactBytes(pwmBuffer, count, IO_TIMEOUT_MS)) {
    Serial.println("ERROR,Timeout waiting for PWM payload");
    return;
  }

  for (unsigned int i = 0; i < count; i++) {
    uint8_t pwm = pwmBuffer[i];
    analogWrite(configuredPwmPin, pwm);
    sampleBuffer[i] = measureAvgAdc(settleUs, oversampleCount, oversampleDelayUs);
  }

  Serial.print("DATA,");
  Serial.println(count);
  Serial.write((uint8_t*)sampleBuffer, (size_t)count * sizeof(uint16_t));
}

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ;
  }

  maxBufferSamples = allocateLargestBuffer();
  if (maxBufferSamples == 0) {
    Serial.println("ERROR,Failed to allocate sample buffer");
    return;
  }

  Serial.println("READY");
}

void loop() {
  if (maxBufferSamples == 0) {
    return;
  }

  if (!readLine()) {
    return;
  }

  if (strncmp(lineBuffer, "SETUP,", 6) == 0) {
    int pwmPin = 9;
    int analogPin = 0;
    if (!parseSetupCommand(lineBuffer, &pwmPin, &analogPin)) {
      Serial.println("ERROR,Invalid SETUP command");
      return;
    }
    configuredPwmPin = pwmPin;
    configuredAnalogPin = analogPin;
    pinMode(configuredPwmPin, OUTPUT);
    isConfigured = true;
    Serial.println("OK_SETUP");
    return;
  }

  if (strcmp(lineBuffer, "CAPS") == 0) {
    Serial.print("CAPS,");
    Serial.println(maxBufferSamples);
    return;
  }

  if (strncmp(lineBuffer, "RUN,", 4) == 0) {
    if (!isConfigured) {
      Serial.println("ERROR,Must call SETUP first");
      return;
    }

    unsigned int count = 0;
    unsigned long settleUs = 0;
    unsigned int oversampleCount = 1;
    unsigned long oversampleDelayUs = 0;
    if (!parseRunCommand(lineBuffer, &count, &settleUs, &oversampleCount, &oversampleDelayUs)) {
      Serial.println("ERROR,Invalid RUN command");
      return;
    }

    runBuffered(count, settleUs, oversampleCount, oversampleDelayUs);
    return;
  }

  Serial.println("ERROR,Unknown command");
}
