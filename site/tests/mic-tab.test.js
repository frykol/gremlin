const test = require('node:test');
const assert = require('node:assert/strict');

const { pcmBase64ToFloat32, levelFromInt16, MAX_SCHEDULE_DRIFT_SECONDS, noiseProfileStatusLabel } = require('../public/tabs/mic.js');

function int16ArrayToBase64(int16) {
  const bytes = new Uint8Array(int16.buffer);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

test('pcmBase64ToFloat32 decodes int16 PCM to normalized float32', () => {
  const int16 = new Int16Array([0, 16384, -32768, 32767]);
  const b64 = int16ArrayToBase64(int16);

  const float32 = pcmBase64ToFloat32(b64);

  assert.equal(float32.length, 4);
  assert.ok(Math.abs(float32[0] - 0) < 1e-6);
  assert.ok(Math.abs(float32[1] - 0.5) < 1e-3);
  assert.ok(Math.abs(float32[2] - -1) < 1e-3);
});

test('levelFromInt16 returns 0 for silence', () => {
  const int16 = new Int16Array([0, 0, 0]);
  assert.equal(levelFromInt16(int16), 0);
});

test('levelFromInt16 returns 100 for full-scale peak', () => {
  const int16 = new Int16Array([0, -32768, 100]);
  assert.equal(levelFromInt16(int16), 100);
});

test('MAX_SCHEDULE_DRIFT_SECONDS is a small positive bound', () => {
  // Guards the fix for playback eventually stalling: once scheduled
  // playback drifts this far ahead of real time (e.g. after the tab was
  // throttled in the background), the schedule resets instead of bursting
  // through a growing backlog.
  assert.ok(MAX_SCHEDULE_DRIFT_SECONDS > 0);
  assert.ok(MAX_SCHEDULE_DRIFT_SECONDS <= 5);
});

test('noiseProfileStatusLabel shows calibrating state first', () => {
  assert.equal(
    noiseProfileStatusLabel({ is_calibrating: true, has_profile: true }),
    'Nagrywanie profilu szumu…'
  );
});

test('noiseProfileStatusLabel shows profile-set state when not calibrating', () => {
  assert.equal(
    noiseProfileStatusLabel({ is_calibrating: false, has_profile: true }),
    'Profil ustawiony'
  );
});

test('noiseProfileStatusLabel shows no-profile state by default', () => {
  assert.equal(
    noiseProfileStatusLabel({ is_calibrating: false, has_profile: false }),
    'Brak profilu'
  );
});
