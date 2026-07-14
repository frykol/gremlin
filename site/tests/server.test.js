const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const { createApp } = require('../server');

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
