const test = require('node:test');
const assert = require('node:assert/strict');

const { GPIO_PINS } = require('../public/tabs/gpio.js');

test('GPIO_PINS maps physical pin 7 to GPIO4', () => {
  assert.equal(GPIO_PINS[7], 'GPIO4');
});

test('GPIO_PINS maps physical pin 37 to GPIO26', () => {
  assert.equal(GPIO_PINS[37], 'GPIO26');
});

test('GPIO_PINS has exactly 13 mapped pins', () => {
  assert.equal(Object.keys(GPIO_PINS).length, 13);
});
