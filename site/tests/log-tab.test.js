const test = require('node:test');
const assert = require('node:assert/strict');

const { classifyLogLine } = require('../public/tabs/log.js');

test('classifyLogLine tags ERROR lines', () => {
  assert.equal(classifyLogLine('2026-07-14 ERROR something broke'), 'log-error');
});

test('classifyLogLine tags CRITICAL lines as error', () => {
  assert.equal(classifyLogLine('CRITICAL failure'), 'log-error');
});

test('classifyLogLine tags SYSTEM lines', () => {
  assert.equal(classifyLogLine('SYSTEM starting up'), 'log-system');
});

test('classifyLogLine tags INFO lines', () => {
  assert.equal(classifyLogLine('INFO all good'), 'log-info');
});

test('classifyLogLine returns null for unmatched lines', () => {
  assert.equal(classifyLogLine('just a plain line'), null);
});

test('classifyLogLine is case-insensitive', () => {
  assert.equal(classifyLogLine('error lowercase'), 'log-error');
});
