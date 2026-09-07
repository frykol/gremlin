const test = require('node:test');
const assert = require('node:assert/strict');

const { classifySystemStatus, parseSystemStatusLog, SYSTEM_STATUS_DEVICES } = require('../public/tabs/system-status.js');

test('classifySystemStatus recognizes success', () => {
  assert.equal(classifySystemStatus('SUCCESS'), 'system-status-success');
});

test('classifySystemStatus recognizes plain error', () => {
  assert.equal(classifySystemStatus('ERROR'), 'system-status-error');
});

test('classifySystemStatus recognizes fallback as distinct from plain error', () => {
  assert.equal(classifySystemStatus('ERROR - FALLBACK TO DUMMY'), 'system-status-fallback');
});

test('classifySystemStatus recognizes intentional dummy mode as distinct from fallback', () => {
  assert.equal(classifySystemStatus('SUCCESS - DUMMY'), 'system-status-dummy');
});

test('classifySystemStatus falls back to unknown for unrecognized text', () => {
  assert.equal(classifySystemStatus('WEIRD'), 'system-status-unknown');
});

test('parseSystemStatusLog keeps the latest status per device', () => {
  const content = 'OAK-D ERROR\nOAK-D ERROR - FALLBACK TO DUMMY\nLIDAR SUCCESS\n';

  const latest = parseSystemStatusLog(content);

  assert.equal(latest['OAK-D'], 'ERROR - FALLBACK TO DUMMY');
  assert.equal(latest['LIDAR'], 'SUCCESS');
});

test('parseSystemStatusLog ignores blank lines', () => {
  const content = '\nOAK-D SUCCESS\n\n';

  const latest = parseSystemStatusLog(content);

  assert.deepEqual(Object.keys(latest), ['OAK-D']);
});

test('SYSTEM_STATUS_DEVICES lists the monitored hardware', () => {
  assert.ok(SYSTEM_STATUS_DEVICES.includes('OAK-D'));
  assert.ok(SYSTEM_STATUS_DEVICES.includes('LIDAR'));
});
