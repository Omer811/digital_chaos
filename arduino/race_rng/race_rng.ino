/*
  Race RNG (method 4): timer-overflow race extractor.

  This is a metastability/race-style sampler: two timer overflow events are
  scheduled very close together; whichever overflow flag appears first emits a bit.

  Protocol:
    RUN,<byte_count>,<progress_every_bytes>\n
  Replies:
    READY
    BEGIN,<byte_count>
    DATA,<index>,<byte_value>
    PROGRESS,<done>,<total>
    END
*/

const unsigned long BAUD_RATE = 115200;
const int MAX_LINE = 48;

char lineBuffer[MAX_LINE];
int lineLength = 0;

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

uint8_t nextRaceBit() {
  // Stop timers.
  TCCR1B = 0;
  TCCR2B = 0;

  // Randomize proximity window from free-running timer0 state.
  // Both timers run at the same tick rate (clk/8), so close preload values create races.
  uint8_t jitter = TCNT0;
  uint8_t baseTicks = 32;
  uint16_t t1TicksToOverflow = (uint16_t)(baseTicks + (jitter & 0x03));
  uint8_t t2TicksToOverflow = (uint8_t)(baseTicks + ((jitter >> 2) & 0x03));

  // Preload counters near overflow.
  TCNT1 = (uint16_t)(65535 - t1TicksToOverflow);
  TCNT2 = (uint8_t)(255 - t2TicksToOverflow);

  // Clear overflow flags.
  TIFR1 = _BV(TOV1);
  TIFR2 = _BV(TOV2);

  // Start both timers with randomized start order to reduce fixed bias.
  if (jitter & 0x01) {
    TCCR1B = _BV(CS11); // clk/8
    TCCR2B = _BV(CS21); // clk/8
  } else {
    TCCR2B = _BV(CS21); // clk/8
    TCCR1B = _BV(CS11); // clk/8
  }

  // Busy-wait for first overflow.
  while (true) {
    uint8_t f1 = (TIFR1 & _BV(TOV1)) ? 1 : 0;
    uint8_t f2 = (TIFR2 & _BV(TOV2)) ? 1 : 0;

    if (f1 && !f2) {
      TCCR1B = 0;
      TCCR2B = 0;
      return 1;
    }
    if (f2 && !f1) {
      TCCR1B = 0;
      TCCR2B = 0;
      return 0;
    }
    if (f1 && f2) {
      // Tie-break using timer jitter.
      TCCR1B = 0;
      TCCR2B = 0;
      return (uint8_t)(TCNT0 & 0x01);
    }
  }
}

uint8_t nextRaceByte() {
  uint8_t value = 0;
  for (int i = 0; i < 8; i++) {
    uint8_t raceBit = nextRaceBit();
    uint8_t jitterBit = (uint8_t)(TCNT0 & 0x01);
    uint8_t mixedBit = (uint8_t)(raceBit ^ jitterBit);
    value = (value << 1) | mixedBit;
  }
  return value;
}

void runSequence(unsigned int byteCount, unsigned int progressEvery) {
  Serial.print("BEGIN,");
  Serial.println(byteCount);

  for (unsigned int i = 0; i < byteCount; i++) {
    uint8_t value = nextRaceByte();

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
