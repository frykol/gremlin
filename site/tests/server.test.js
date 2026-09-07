const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const { createApp } = require('../server');

test('GET /api/sounds lists mp3/wav files from the sounds directory', async () => {
  const soundsDir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'sounds-'));
  fs.writeFileSync(path.join(soundsDir, 'b.mp3'), '');
  fs.writeFileSync(path.join(soundsDir, 'a.wav'), '');
  fs.writeFileSync(path.join(soundsDir, 'ignore.txt'), '');

  const app = createApp({ soundsDir });
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/api/sounds`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });

  assert.deepEqual(body.sounds, ['a.wav', 'b.mp3']);

  await new Promise((resolve) => server.close(resolve));
  fs.rmSync(soundsDir, { recursive: true, force: true });
});

test('GET /sounds/<file> serves a file from the sounds directory', async () => {
  const soundsDir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'sounds-'));
  fs.writeFileSync(path.join(soundsDir, 'test.mp3'), 'fake-audio-bytes');

  const app = createApp({ soundsDir });
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/sounds/test.mp3`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });

  assert.equal(body, 'fake-audio-bytes');

  await new Promise((resolve) => server.close(resolve));
  fs.rmSync(soundsDir, { recursive: true, force: true });
});

test('createApp serves the static index page', async () => {
  const publicDir = path.join(__dirname, '..', 'public');
  assert.ok(fs.existsSync(path.join(publicDir, 'index.html')), 'public/index.html must exist');

  const app = createApp();
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });

  assert.ok(body.includes('<'), 'expected HTML content from index page');

  await new Promise((resolve) => server.close(resolve));
});
