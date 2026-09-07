const test = require('node:test');
const assert = require('node:assert/strict');

const { colorDetectionStatusLabel, greenOnYellowStatusLabel } = require('../public/tabs/color-detection.js');

test('colorDetectionStatusLabel returns TAK when blue detected', () => {
  assert.equal(colorDetectionStatusLabel(true), 'TAK');
});

test('colorDetectionStatusLabel returns NIE when blue not detected', () => {
  assert.equal(colorDetectionStatusLabel(false), 'NIE');
});

test('greenOnYellowStatusLabel returns TAK when detected', () => {
  assert.equal(greenOnYellowStatusLabel(true), 'TAK');
});

test('greenOnYellowStatusLabel returns NIE when not detected', () => {
  assert.equal(greenOnYellowStatusLabel(false), 'NIE');
});
