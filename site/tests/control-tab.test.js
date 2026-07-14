const test = require('node:test');
const assert = require('node:assert/strict');

const { computeChannelValues, recalcDirections } = require('../public/tabs/control.js');

test('computeChannelValues drives front-left/front-right channels forward for Przód', () => {
  const values = computeChannelValues(new Set(['Przód']), 100);
  assert.equal(values[0], 100);
  assert.equal(values[1], 0);
  assert.equal(values[2], 100);
  assert.equal(values[3], 0);
  assert.equal(values[5], 100);
  assert.equal(values[4], 0);
  assert.equal(values[7], 100);
  assert.equal(values[6], 0);
});

test('computeChannelValues drives reverse channels for Tył', () => {
  const values = computeChannelValues(new Set(['Tył']), 50);
  assert.equal(values[1], 50);
  assert.equal(values[0], 0);
  assert.equal(values[3], 50);
  assert.equal(values[2], 0);
});

test('computeChannelValues is all-zero with no active directions', () => {
  const values = computeChannelValues(new Set(), 100);
  for (let i = 0; i < 8; i++) {
    assert.equal(values[i], 0);
  }
});

test('recalcDirections maps arrow keys to direction names', () => {
  const dirs = recalcDirections(new Set(), new Set(['Up']));
  assert.ok(dirs.has('Przód'));
});

test('recalcDirections maps Shift+Left to Full lewo instead of Lewo', () => {
  const dirs = recalcDirections(new Set(), new Set(['Left', 'Shift']));
  assert.ok(dirs.has('Full lewo'));
  assert.ok(!dirs.has('Lewo'));
});

test('recalcDirections includes pressed buttons unchanged', () => {
  const dirs = recalcDirections(new Set(['Prawo']), new Set());
  assert.ok(dirs.has('Prawo'));
});
