const express = require('express');
const path = require('path');
const dgram = require('dgram');
const { WebSocketServer } = require('ws');

function createApp() {
  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  return app;
}

function createVideoRelay(udpPort) {
  const wss = new WebSocketServer({ noServer: true });
  let browserSocket = null;

  wss.on('connection', (ws) => {
    browserSocket = ws;
    ws.on('close', () => {
      if (browserSocket === ws) {
        browserSocket = null;
      }
    });
  });

  const udpSocket = dgram.createSocket('udp4');
  udpSocket.on('message', (msg) => {
    if (browserSocket && browserSocket.readyState === browserSocket.OPEN) {
      browserSocket.send(msg);
    }
  });
  udpSocket.bind(udpPort);

  return { wss, udpSocket };
}

module.exports = { createApp, createVideoRelay };

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const UDP_PORT = process.env.UDP_PORT || 9000;

  const app = createApp();
  const server = app.listen(PORT, () => {
    console.log(`Control site listening on :${PORT}`);
  });

  const { wss } = createVideoRelay(UDP_PORT);

  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/video') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    } else {
      socket.destroy();
    }
  });

  console.log(`UDP video relay listening on :${UDP_PORT}`);
}
