/*
  MCP23017 floating GPIO sampler for Arduino UNO.

  Protocol:
    RUN,<sample_count>,<delay_us>,<progress_every_samples>,<i2c_address>

  Replies:
    READY
    BEGIN,<sample_count>
    DATA,<index>,<gpioa_byte>,<gpiob_byte>
    PROGRESS,<done>,<total>
    END
*/

#include <Wire.h>

const unsigned long BAUD_RATE = 115200;
const int MAX_LINE = 80;

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
  unsigned int* sampleCount,
  unsigned long* delayUs,
  unsigned int* progressEvery,
  uint8_t* i2cAddress
) {
  char* token = strtok(input, ",");
  if (token == NULL || strcmp(token, "RUN") != 0) {
    return false;
  }

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *sampleCount = (unsigned int)atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *delayUs = strtoul(token, NULL, 10);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *progressEvery = (unsigned int)atoi(token);

  token = strtok(NULL, ",");
  if (token == NULL) return false;
  *i2cAddress = (uint8_t)strtoul(token, NULL, 0);

  return true;
}

bool writeRegister(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return (Wire.endTransmission() == 0);
}

bool readRegisters(uint8_t addr, uint8_t reg, uint8_t count, uint8_t* out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  uint8_t readCount = Wire.requestFrom((int)addr, (int)count);
  if (readCount != count) {
    return false;
  }

  for (uint8_t i = 0; i < count; i++) {
    out[i] = Wire.read();
  }
  return true;
}

bool setupMCP23017(uint8_t addr) {
  // IODIR: all inputs.
  if (!writeRegister(addr, 0x00, 0xFF)) return false; // IODIRA
  if (!writeRegister(addr, 0x01, 0xFF)) return false; // IODIRB

  // GPPU: all pull-ups disabled to keep pins floating.
  if (!writeRegister(addr, 0x0C, 0x00)) return false; // GPPUA
  if (!writeRegister(addr, 0x0D, 0x00)) return false; // GPPUB

  return true;
}

void runSequence(unsigned int sampleCount, unsigned long delayUs, unsigned int progressEvery, uint8_t i2cAddress) {
  Serial.print("BEGIN,");
  Serial.println(sampleCount);

  for (unsigned int i = 0; i < sampleCount; i++) {
    uint8_t values[2] = {0, 0};
    if (!readRegisters(i2cAddress, 0x12, 2, values)) {
      Serial.println("ERROR,Failed reading GPIO registers");
      return;
    }

    Serial.print("DATA,");
    Serial.print(i);
    Serial.print(",");
    Serial.print(values[0]);
    Serial.print(",");
    Serial.println(values[1]);

    if (progressEvery > 0 && (((i + 1) % progressEvery) == 0 || (i + 1) == sampleCount)) {
      Serial.print("PROGRESS,");
      Serial.print(i + 1);
      Serial.print(",");
      Serial.println(sampleCount);
    }

    if (delayUs > 0) {
      delayMicroseconds(delayUs);
    }
  }

  Serial.println("END");
}

void setup() {
  Wire.begin();
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

  unsigned int sampleCount = 0;
  unsigned long delayUs = 0;
  unsigned int progressEvery = 0;
  uint8_t i2cAddress = 0x20;

  if (!parseRunCommand(lineBuffer, &sampleCount, &delayUs, &progressEvery, &i2cAddress)) {
    Serial.println("ERROR,Invalid command");
    return;
  }

  if (!setupMCP23017(i2cAddress)) {
    Serial.println("ERROR,Failed configuring MCP23017 (check wiring/address)");
    return;
  }

  runSequence(sampleCount, delayUs, progressEvery, i2cAddress);
}
