const test = require('node:test');
const assert = require('node:assert/strict');

const { pwmFromPercent, oppositeChannel, I2C_LABELS } = require('../public/tabs/i2c.js');

test('pwmFromPercent converts 0-100 range to 0-4095', () => {
  assert.equal(pwmFromPercent(0), 0);
  assert.equal(pwmFromPercent(100), 4095);
  assert.equal(pwmFromPercent(50), Math.round(50 * 40.95));
});

test('oppositeChannel pairs 0<->1, 2<->3, 4<->5, 6<->7', () => {
  assert.equal(oppositeChannel(0), 1);
  assert.equal(oppositeChannel(1), 0);
  assert.equal(oppositeChannel(6), 7);
  assert.equal(oppositeChannel(7), 6);
});

test('I2C_LABELS has 8 entries matching the old Tkinter labels', () => {
  assert.equal(I2C_LABELS.length, 8);
  assert.equal(I2C_LABELS[0], 'LP przód');
  assert.equal(I2C_LABELS[7], 'PT przód');
});
