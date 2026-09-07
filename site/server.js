const express = require('express');
const path = require('path');
const fs = require('fs');
const dgram = require('dgram');
const { WebSocketServer } = require('ws');

function createApp(options = {}) {
  const udpPort = options.udpPort || Number(process.env.UDP_PORT) || 9000;
  const configPath = options.configPath || path.join(__dirname, '..', 'config.json');
  const soundsDir = options.soundsDir || path.join(__dirname, '..', 'sounds');

  const app = express();
  app.use(express.json());
  app.use('/sounds', express.static(soundsDir));
  app.use(express.static(path.join(__dirname, 'public'), {
    // Skrypty tabow (np. lidar.js/ai.js) zmieniaja sie czesto podczas
    // rozwoju - bez tego przegladarka potrafi trzymac stara wersje w
    // cache'u HTTP i strona dziala na nieaktualnym kodzie mimo zmian na
    // dysku (widoczne np. jako stare kolorowanie chmury punktow po
    // deployu nowej wersji).
    setHeaders: (res, filePath) => {
      if (filePath.endsWith('.js')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
    },
  }));
  app.get('/api/config', (req, res) => {
    res.json({ udpPort });
  });

  app.get('/api/robot-config', (req, res) => {
    let raw;
    try {
      raw = fs.readFileSync(configPath, 'utf8');
    } catch (e) {
      res.status(404).json({ error: `Config file not found: ${e.message}` });
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      res.status(500).json({ error: `Config file is not valid JSON: ${e.message}` });
      return;
    }

    res.json(parsed);
  });

  app.get('/api/sounds', (req, res) => {
    let entries;
    try {
      entries = fs.readdirSync(soundsDir);
    } catch (e) {
      res.json({ sounds: [] });
      return;
    }

    const sounds = entries
      .filter((name) => /\.(mp3|wav)$/i.test(name))
      .sort();

    res.json({ sounds });
  });

  app.put('/api/robot-config', (req, res) => {
    const body = req.body;
    const isPlainObject = body !== null && typeof body === 'object' && !Array.isArray(body);
    if (!isPlainObject) {
      res.status(400).json({ error: 'Request body must be a JSON object' });
      return;
    }

    try {
      fs.writeFileSync(configPath, JSON.stringify(body, null, 2) + '\n');
    } catch (e) {
      res.status(500).json({ error: `Failed to write config file: ${e.message}` });
      return;
    }

    res.json({ success: true });
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
  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.error(
        `Port ${PORT} jest juz zajety - prawdopodobnie stary proces server.js` +
        ` nadal dziala. Zabij go przed restartem: sudo lsof -i :${PORT} (albo` +
        ` sudo fuser -k ${PORT}/tcp) i sprobuj ponownie.`
      );
      process.exit(1);
    }
    throw err;
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
