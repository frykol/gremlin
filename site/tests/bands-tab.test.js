const test = require('node:test');
const assert = require('node:assert/strict');

const { bandStatusLabel } = require('../public/tabs/bands.js');

test('bandStatusLabel returns TAK when both bands detected', () => {
  assert.equal(bandStatusLabel(true), 'TAK');
});

test('bandStatusLabel returns NIE when not both bands detected', () => {
  assert.equal(bandStatusLabel(false), 'NIE');
});
