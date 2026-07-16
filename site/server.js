const express = require('express');
const path = require('path');
const dgram = require('dgram');
const { WebSocketServer } = require('ws');

function createApp(options = {}) {
  const udpPort = options.udpPort || Number(process.env.UDP_PORT) || 9000;

  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  app.get('/api/config', (req, res) => {
    res.json({ udpPort });
  });
  return app;
}

function createVideoRelay(udpPort) {
  const wss = new WebSocketServer({ noServer: true });
  let browserSocket = null;
  const pendingFrames = new Map();
  const HEADER_SIZE = 4 + 2 + 2 + 8;

  const sendToBrowser = (payload) => {
    if (browserSocket && browserSocket.readyState === browserSocket.OPEN) {
      browserSocket.send(payload);
    }
  };

  const parseUdpFrame = (msg) => {
    if (msg.length < HEADER_SIZE) {
      return {
        frameId: null,
        chunkIndex: 0,
        totalChunks: 1,
        payload: msg,
      };
    }

    const frameId = msg.readUInt32BE(0);
    const chunkIndex = msg.readUInt16BE(4);
    const totalChunks = msg.readUInt16BE(6);
    const payload = msg.subarray(HEADER_SIZE);

    return {
      frameId,
      chunkIndex,
      totalChunks,
      payload,
    };
  };

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
    const { frameId, chunkIndex, totalChunks, payload } = parseUdpFrame(msg);

    if (frameId === null || totalChunks <= 1) {
      sendToBrowser(payload);
      return;
    }

    const pendingFrame = pendingFrames.get(frameId) || {
      chunks: [],
      totalChunks,
      received: 0,
    };

    pendingFrame.chunks[chunkIndex] = payload;
    pendingFrame.received += 1;

    if (pendingFrame.received === pendingFrame.totalChunks) {
      const fullPayload = Buffer.concat(pendingFrame.chunks);
      pendingFrames.delete(frameId);
      sendToBrowser(fullPayload);
      return;
    }

    pendingFrames.set(frameId, pendingFrame);
  });
  udpSocket.bind(udpPort);

  return { wss, udpSocket };
}

module.exports = { createApp, createVideoRelay };

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const UDP_PORT = process.env.UDP_PORT || 9000;

  const app = createApp({ udpPort: UDP_PORT });
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
