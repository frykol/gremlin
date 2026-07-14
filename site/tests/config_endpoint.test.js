const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const { createApp } = require('../server');

test('GET /api/config returns the configured UDP port', async () => {
  const app = createApp({ udpPort: 9123 });
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/api/config`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });

  assert.deepEqual(JSON.parse(body), { udpPort: 9123 });

  await new Promise((resolve) => server.close(resolve));
});
