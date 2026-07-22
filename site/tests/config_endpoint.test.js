const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

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

function makeTempConfigPath(name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gremlin-config-test-'));
  return path.join(dir, name);
}

function httpRequest(port, method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : JSON.stringify(body);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: urlPath,
        method,
        headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
      },
      (res) => {
        let chunks = '';
        res.on('data', (chunk) => { chunks += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, body: chunks }));
      }
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

test('GET /api/robot-config returns the parsed config file', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true, gpio: { chip: '/dev/gpiochip0' } }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 200);
  assert.deepEqual(JSON.parse(body), { dev: true, gpio: { chip: '/dev/gpiochip0' } });

  await new Promise((resolve) => server.close(resolve));
});

test('GET /api/robot-config returns 404 when the file is missing', async () => {
  const configPath = makeTempConfigPath('missing-config.json');

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 404);
  assert.ok(JSON.parse(body).error);

  await new Promise((resolve) => server.close(resolve));
});

test('GET /api/robot-config returns 500 when the file has invalid JSON', async () => {
  const configPath = makeTempConfigPath('bad-config.json');
  fs.writeFileSync(configPath, '{ not valid json');

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 500);
  assert.ok(JSON.parse(body).error);

  await new Promise((resolve) => server.close(resolve));
});

test('PUT /api/robot-config writes the body to disk and returns success', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'PUT', '/api/robot-config', { dev: false, gpio: { chip: '/dev/gpiochip1' } });

  assert.equal(status, 200);
  assert.deepEqual(JSON.parse(body), { success: true });
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath, 'utf8')), { dev: false, gpio: { chip: '/dev/gpiochip1' } });

  await new Promise((resolve) => server.close(resolve));
});

test('PUT /api/robot-config returns 400 for a non-object body', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'PUT', '/api/robot-config', [1, 2, 3]);

  assert.equal(status, 400);
  assert.ok(JSON.parse(body).error);
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath, 'utf8')), { dev: true });

  await new Promise((resolve) => server.close(resolve));
});
