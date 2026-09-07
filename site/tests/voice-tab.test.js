const test = require('node:test');
const assert = require('node:assert/strict');

const { formatVoiceTime } = require('../public/tabs/voice.js');

test('formatVoiceTime returns empty string for falsy input', () => {
  assert.equal(formatVoiceTime(0), '');
  assert.equal(formatVoiceTime(null), '');
});

test('formatVoiceTime returns a non-empty time string for a timestamp', () => {
  assert.notEqual(formatVoiceTime(1700000000), '');
});
