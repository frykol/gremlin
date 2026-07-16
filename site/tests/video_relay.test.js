const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const dgram = require('node:dgram');
const WebSocket = require('ws');

const { createApp, createVideoRelay } = require('../server');

test('UDP datagrams are relayed to the connected video WS client', async () => {
  const app = createApp();
  const server = http.createServer(app);
  const { wss, udpSocket } = createVideoRelay(0);

  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/video') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    } else {
      socket.destroy();
    }
  });

  await new Promise((resolve) => server.listen(0, resolve));
  const { port: httpPort } = server.address();
  const udpPort = udpSocket.address().port;

  const client = new WebSocket(`ws://127.0.0.1:${httpPort}/video`);
  await new Promise((resolve, reject) => {
    client.on('open', resolve);
    client.on('error', reject);
  });

  const received = new Promise((resolve) => {
    client.on('message', (data) => resolve(data));
  });

  const sender = dgram.createSocket('udp4');
  const payload = Buffer.from('fake-jpeg-frame-bytes');
  sender.send(payload, udpPort, '127.0.0.1');

  const message = await received;
  assert.deepEqual(Buffer.from(message), payload);

  sender.close();
  client.close();
  udpSocket.close();
  await new Promise((resolve) => server.close(resolve));
});

test('createVideoRelay reassembles chunked UDP frames before forwarding them to the browser', async () => {
  const app = createApp();
  const server = http.createServer(app);
  const { wss, udpSocket } = createVideoRelay(0);

  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/video') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    } else {
      socket.destroy();
    }
  });

  await new Promise((resolve) => server.listen(0, resolve));
  const { port: httpPort } = server.address();
  const udpPort = udpSocket.address().port;

  const client = new WebSocket(`ws://127.0.0.1:${httpPort}/video`);
  await new Promise((resolve, reject) => {
    client.on('open', resolve);
    client.on('error', reject);
  });

  const messages = [];
  client.on('message', (data) => messages.push(Buffer.from(data)));

  const sender = dgram.createSocket('udp4');
  const payload = Buffer.from('fake-jpeg-frame-bytes');
  const frameId = 7;
  const chunkSize = 10;
  const firstChunk = payload.subarray(0, chunkSize);
  const secondChunk = payload.subarray(chunkSize);

  const makeHeader = (chunkIndex, totalChunks) => {
    const header = Buffer.alloc(4 + 2 + 2 + 8);
    header.writeUInt32BE(frameId, 0);
    header.writeUInt16BE(chunkIndex, 4);
    header.writeUInt16BE(totalChunks, 6);
    header.writeDoubleBE(1.5, 8);
    return header;
  };

  sender.send(Buffer.concat([makeHeader(0, 2), firstChunk]), udpPort, '127.0.0.1');
  sender.send(Buffer.concat([makeHeader(1, 2), secondChunk]), udpPort, '127.0.0.1');

  await new Promise((resolve) => setTimeout(resolve, 100));

  assert.deepEqual(messages, [payload]);

  sender.close();
  client.close();
  udpSocket.close();
  await new Promise((resolve) => server.close(resolve));
});

test('createVideoRelay drops datagrams when no client is connected', async () => {
  const { udpSocket } = createVideoRelay(0);
  // dgram binds asynchronously; wait for it to finish before reading the
  // ephemeral port, otherwise address() throws EBADF (unbound socket).
  await new Promise((resolve) => udpSocket.once('listening', resolve));
  const udpPort = udpSocket.address().port;

  const sender = dgram.createSocket('udp4');
  sender.send(Buffer.from('no-one-listening'), udpPort, '127.0.0.1');

  await new Promise((resolve) => setTimeout(resolve, 50));

  sender.close();
  udpSocket.close();
});
