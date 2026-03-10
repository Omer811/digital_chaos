/*
  Jitter RNG (method 3): watchdog-timer jitter sampled against Timer1.

  Protocol:
    RUN,<byte_count>,<progress_every_bytes>\n
  Replies:
    READY
    BEGIN,<byte_count>
    DATA,<index>,<byte_value>
    PROGRESS,<done>,<total>
    END
*/

#include <avr/wdt.h>

const unsigned long BAUD_RATE = 115200;
const int MAX_LINE = 48;

char lineBuffer[MAX_LINE];
int lineLength = 0;

volatile bool wdtFired = false;
volatile uint16_t wdtCapture = 0;

ISR(WDT_vect) {
  wdtCapture = TCNT1;
  wdtFired = true;
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

bool parseRunCommand(char* input, unsigned int* byteCount, unsigned int* progressEvery) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "RUN") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *byteCount = (unsigned int)atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *progressEvery = (unsigned int)atoi(token);

  return true;
}

void setupJitterSource() {
  TCCR1A = 0;
  TCCR1B = _BV(CS10);
  TCNT1 = 0;

  MCUSR &= ~_BV(WDRF);
  WDTCSR = _BV(WDCE) | _BV(WDE);
  WDTCSR = _BV(WDIE);
}

uint8_t nextJitterBit(uint16_t* lastCapture) {
  while (!wdtFired) {
    ;
  }

  noInterrupts();
  uint16_t capture = wdtCapture;
  wdtFired = false;
  interrupts();

  uint16_t delta = capture - *lastCapture;
  *lastCapture = capture;

  uint16_t mixed = delta ^ capture ^ (capture >> 3) ^ (delta << 2);
  return (uint8_t)(mixed & 0x01);
}

uint8_t nextJitterByte(uint16_t* lastCapture) {
  uint8_t value = 0;
  for (int i = 0; i < 8; i++) {
    value = (value << 1) | nextJitterBit(lastCapture);
  }
  return value;
}

void runSequence(unsigned int byteCount, unsigned int progressEvery) {
  Serial.print("BEGIN,");
  Serial.println(byteCount);

  while (!wdtFired) {
    ;
  }
  noInterrupts();
  uint16_t lastCapture = wdtCapture;
  wdtFired = false;
  interrupts();

  for (unsigned int i = 0; i < byteCount; i++) {
    uint8_t value = nextJitterByte(&lastCapture);

    Serial.print("DATA,");
    Serial.print(i);
    Serial.print(",");
    Serial.println(value);

    if (progressEvery > 0 && (((i + 1) % progressEvery) == 0 || (i + 1) == byteCount)) {
      Serial.print("PROGRESS,");
      Serial.print(i + 1);
      Serial.print(",");
      Serial.println(byteCount);
    }
  }

  Serial.println("END");
}

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    ;
  }
  setupJitterSource();
  Serial.println("READY");
}

void loop() {
  if (!readLine()) {
    return;
  }

  unsigned int byteCount = 0;
  unsigned int progressEvery = 0;

  if (!parseRunCommand(lineBuffer, &byteCount, &progressEvery)) {
    Serial.println("ERROR,Invalid command");
    return;
  }

  runSequence(byteCount, progressEvery);
}
