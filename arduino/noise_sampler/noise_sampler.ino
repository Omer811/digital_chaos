/*
  Arduino UNO random-noise sampler.
  Protocol:
    Host sends:
      START,<sample_count>,<pin_count>,<pin0>,...,<pinN>,<row_delay_us>,<channel_settle_us>,<throwaway_reads_after_switch>,<progress_every_samples>\n
    Device replies:
      BEGIN,<sample_count>,<pin_count>
      PROGRESS,<completed_samples>,<sample_count>
      DATA,<index>,<v0>,<v1>,...,<vN>
      END
*/

const unsigned long BAUD_RATE = 115200;
const int MAX_PINS = 6;
const int MAX_LINE = 128;

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

bool parseStartCommand(
  char* input,
  unsigned long* sampleCount,
  int* pinCount,
  int pinNumbers[],
  unsigned long* rowDelayUs,
  unsigned long* channelSettleUs,
  int* throwawayReadsAfterSwitch,
  unsigned long* progressEverySamples
) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "START") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *sampleCount = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *pinCount = atoi(token);

  if (*pinCount <= 0 || *pinCount > MAX_PINS) {
    return false;
  }

  for (int i = 0; i < *pinCount; i++) {
    token = strtok(NULL, ",");
    if (token == NULL) {
      return false;
    }
    int pinNumber = atoi(token);
    if (pinNumber < 0 || pinNumber > 5) {
      return false;
    }
    pinNumbers[i] = pinNumber;
  }

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *rowDelayUs = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *channelSettleUs = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *throwawayReadsAfterSwitch = atoi(token);
  if (*throwawayReadsAfterSwitch < 0 || *throwawayReadsAfterSwitch > 16) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) {
    return false;
  }
  *progressEverySamples = strtoul(token, NULL, 10);

  return true;
}

int readSettledAnalog(int analogPin, unsigned long channelSettleUs, int throwawayReadsAfterSwitch) {
  analogRead(analogPin);
  if (channelSettleUs > 0) {
    delayMicroseconds(channelSettleUs);
  }

  for (int i = 0; i < throwawayReadsAfterSwitch; i++) {
    analogRead(analogPin);
    if (channelSettleUs > 0) {
      delayMicroseconds(channelSettleUs);
    }
  }

  return analogRead(analogPin);
}

void emitData(
  unsigned long sampleCount,
  int pinCount,
  int pinNumbers[],
  unsigned long rowDelayUs,
  unsigned long channelSettleUs,
  int throwawayReadsAfterSwitch,
  unsigned long progressEverySamples
) {
  Serial.print("BEGIN,");
  Serial.print(sampleCount);
  Serial.print(",");
  Serial.println(pinCount);

  for (unsigned long sampleIndex = 0; sampleIndex < sampleCount; sampleIndex++) {
    Serial.print("DATA,");
    Serial.print(sampleIndex);

    for (int i = 0; i < pinCount; i++) {
      int analogPin = A0 + pinNumbers[i];
      int value = readSettledAnalog(analogPin, channelSettleUs, throwawayReadsAfterSwitch);
      Serial.print(",");
      Serial.print(value);
    }

    Serial.println();

    if (progressEverySamples > 0 && ((sampleIndex + 1) % progressEverySamples == 0 || (sampleIndex + 1) == sampleCount)) {
      Serial.print("PROGRESS,");
      Serial.print(sampleIndex + 1);
      Serial.print(",");
      Serial.println(sampleCount);
    }

    if (rowDelayUs > 0) {
      delayMicroseconds(rowDelayUs);
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

  unsigned long sampleCount = 0;
  int pinCount = 0;
  int pinNumbers[MAX_PINS];
  unsigned long rowDelayUs = 0;
  unsigned long channelSettleUs = 0;
  int throwawayReadsAfterSwitch = 0;
  unsigned long progressEverySamples = 0;

  if (!parseStartCommand(
        lineBuffer,
        &sampleCount,
        &pinCount,
        pinNumbers,
        &rowDelayUs,
        &channelSettleUs,
        &throwawayReadsAfterSwitch,
        &progressEverySamples)) {
    Serial.println("ERROR,Invalid command");
    return;
  }

  emitData(
    sampleCount,
    pinCount,
    pinNumbers,
    rowDelayUs,
    channelSettleUs,
    throwawayReadsAfterSwitch,
    progressEverySamples);
}
