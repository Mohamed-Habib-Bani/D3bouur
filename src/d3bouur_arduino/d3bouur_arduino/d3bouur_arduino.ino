#include "AFMotor_R4.h"
#include <Servo.h>

AF_DCMotor motor1(1);
AF_DCMotor motor2(2);
AF_DCMotor motor3(3);
AF_DCMotor motor4(4);

AF_DCMotor* motors[4] = {&motor1, &motor2, &motor3, &motor4};
bool reversed[4] = {true, false, true, false};

Servo headServo;

const int trigPin = 9;
const int echoPins[6] = {A4, A5, A0, A1, A2, A3};

unsigned long lastSensorRead = 0;
const unsigned long sensorInterval = 250;

char inputBuffer[64];
int bufferIndex = 0;

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 4; i++) {
    motors[i]->setSpeed(0);
    motors[i]->run(RELEASE);
  }
  headServo.attach(10);
  headServo.write(90);
  pinMode(trigPin, OUTPUT);
  for (int i = 0; i < 6; i++) pinMode(echoPins[i], INPUT);
  Serial.println("READY");
}

void setMotor(int index, int value) {
  if (reversed[index]) value = -value;
  if (value > 0) {
    motors[index]->setSpeed(min(value, 255));
    motors[index]->run(FORWARD);
  } else if (value < 0) {
    motors[index]->setSpeed(min(-value, 255));
    motors[index]->run(BACKWARD);
  } else {
    motors[index]->run(RELEASE);
  }
}

void stopAllMotors() {
  for (int i = 0; i < 4; i++) motors[i]->run(RELEASE);
  headServo.write(90);
}

void processLine(char* line) {
  if (line[0] == 'X') {
    stopAllMotors();
    return;
  }

  // Single-character Bluetooth commands (F/B/L/R/S) - HC-05 manual control mode
  if (line[0] == 'F' && line[1] == '\0') {
    setMotor(0, 150);
    setMotor(1, 150);
    setMotor(2, 150);
    setMotor(3, 150);
    return;
  }
  if (line[0] == 'B' && line[1] == '\0') {
    setMotor(0, -150);
    setMotor(1, -150);
    setMotor(2, -150);
    setMotor(3, -150);
    return;
  }
  if (line[0] == 'L' && line[1] == '\0') {
    setMotor(0, -100);
    setMotor(1, 150);
    setMotor(2, -100);
    setMotor(3, 150);
    return;
  }
  if (line[0] == 'R' && line[1] == '\0') {
    setMotor(0, 150);
    setMotor(1, -100);
    setMotor(2, 150);
    setMotor(3, -100);
    return;
  }
  if (line[0] == 'S' && line[1] == '\0') {
    stopAllMotors();
    return;
  }

  // Original M:/S: protocol (used with the Pi over USB serial)
  if (line[1] != ':') {
    return;
  }

  char type = line[0];
  char* data = line + 2;

  if (type == 'M') {
    int values[4];
    int count = 0;
    char* token = strtok(data, ",");
    while (token != NULL && count < 4) {
      values[count] = atoi(token);
      count++;
      token = strtok(NULL, ",");
    }
    if (count == 4) {
      for (int i = 0; i < 4; i++) setMotor(i, values[i]);
    }
  }
  else if (type == 'S') {
    int val = atoi(data);
    val = constrain(val, 0, 180);
    headServo.write(val);
  }
}

void readAndSendSensors() {
  Serial.print("D:");
  for (int i = 0; i < 6; i++) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);
    long duration = pulseIn(echoPins[i], HIGH, 30000);
    float distanceCm = duration * 0.034 / 2;
    if (duration == 0) Serial.print("-1");
    else Serial.print(distanceCm, 1);
    if (i < 5) Serial.print(",");
  }
  Serial.println();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputBuffer[bufferIndex] = '\0';
      processLine(inputBuffer);
      bufferIndex = 0;
    } else if (bufferIndex < 63) {
      inputBuffer[bufferIndex] = c;
      bufferIndex++;
    }
  }

  unsigned long now = millis();
  if (now - lastSensorRead >= sensorInterval) {
    lastSensorRead = now;
    readAndSendSensors();
  }
}
