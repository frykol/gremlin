const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const publicDir = path.join(__dirname, '..', 'public');

test('ESP LiDAR tab exposes protocol controls', () => {
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  const tab = fs.readFileSync(path.join(publicDir, 'tabs', 'esp-lidar.js'), 'utf8');

  assert.match(html, /id="esp-lidar-control"/);
  assert.match(html, /id="esp-lidar-stream-mask"/);
  assert.match(html, /id="esp-lidar-clear-history"/);
  assert.match(tab, /api\/esp_lidar\/command/);
  assert.match(tab, /set_stream_mask/);
  assert.match(tab, /clear_history/);
  assert.match(tab, /api\/esp_lidar\/status/);
});