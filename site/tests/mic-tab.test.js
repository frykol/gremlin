const test = require('node:test');
const assert = require('node:assert/strict');

const { pcmBase64ToFloat32, levelFromInt16 } = require('../public/tabs/mic.js');

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
