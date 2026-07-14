const test = require('node:test');
const assert = require('node:assert/strict');

const { nextRotationClass } = require('../public/tabs/camera.js');

test('nextRotationClass toggles from empty to rotated', () => {
  assert.equal(nextRotationClass(''), 'rotated');
});

test('nextRotationClass toggles from rotated back to empty', () => {
  assert.equal(nextRotationClass('rotated'), '');
});
