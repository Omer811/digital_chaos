/*
  Self-feedback sampler (Arduino UNO).
  Wire A0 -> A1 externally.

  Protocol:
    Host sends:
      RUN,<sample_count>,<initial_state>,<threshold>,<settle_us>,<progress_every_samples>\n
    Device replies:
      READY
      BEGIN,<sample_count>
      DATA,<index>,<emitted_state>,<read_value>
      PROGRESS,<completed_samples>,<sample_count>
      END
*/

const unsigned long BAUD_RATE = 115200;
const int MAX_LINE = 96;

const int OUT_PIN = A0;
const int IN_PIN = A1;

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

bool parseRunCommand(
  char* input,
  unsigned long* sampleCount,
  int* initialState,
  int* threshold,
  unsigned long* settleUs,
  unsigned long* progressEvery
) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "RUN") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *sampleCount = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *initialState = atoi(token);
  if (*initialState != 0 && *initialState != 1) return false;

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *threshold = atoi(token);
  if (*threshold < 0 || *threshold > 1023) return false;

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *settleUs = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *progressEvery = strtoul(token, NULL, 10);

  return true;
}

void runSequence(
  unsigned long sampleCount,
  int initialState,
  int threshold,
  unsigned long settleUs,
  unsigned long progressEvery
) {
  int state = initialState;

  Serial.print("BEGIN,");
  Serial.println(sampleCount);

  for (unsigned long i = 0; i < sampleCount; i++) {
    digitalWrite(OUT_PIN, state == 1 ? HIGH : LOW);

    if (settleUs > 0) {
      delayMicroseconds(settleUs);
    }

    int readValue = analogRead(IN_PIN);

    Serial.print("DATA,");
    Serial.print(i);
    Serial.print(",");
    Serial.print(state);
    Serial.print(",");
    Serial.println(readValue);

    if (progressEvery > 0 && (((i + 1) % progressEvery) == 0 || (i + 1) == sampleCount)) {
      Serial.print("PROGRESS,");
      Serial.print(i + 1);
      Serial.print(",");
      Serial.println(sampleCount);
    }

    state = (readValue >= threshold) ? 1 : 0;
  }

  Serial.println("END");
}

void setup() {
  pinMode(OUT_PIN, OUTPUT);
  pinMode(IN_PIN, INPUT);
  digitalWrite(OUT_PIN, LOW);

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

  unsigned long sampleCount = 0;
  int initialState = 1;
  int threshold = 512;
  unsigned long settleUs = 1000;
  unsigned long progressEvery = 10;

  if (!parseRunCommand(
        lineBuffer,
        &sampleCount,
        &initialState,
        &threshold,
        &settleUs,
        &progressEvery)) {
    Serial.println("ERROR,Invalid command");
    return;
  }

  runSequence(sampleCount, initialState, threshold, settleUs, progressEvery);
}
