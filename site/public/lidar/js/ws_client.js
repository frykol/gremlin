// gremlin/lidar_viewer/frontend/js/ws_client.js
/**
 * Dekoduje wiadomosci WS z backendu lidar_viewer. Format wg
 * backend/ws_server.py: Scan/IMU binarnie (naglowek uint32 zawsze
 * wyrownany do 4 bajtow, zeby Float32Array nie rzucal RangeError),
 * metryki jako tekst JSON.
 */

const SCAN_WS_TYPE = 1;
const IMU_WS_TYPE = 2;
const OBSTACLES_WS_TYPE = 3;
const OBSTACLE_RECORD_FLOATS = 12; // x_min,x_max,y_min,y_max,z_min,z_max,cx,cy,cz,point_count,mean_intensity,anomaly_score

function decodeMessage(data) {
  if (typeof data === 'string') {
    const parsed = JSON.parse(data);
    return {
      type: 'metrics',
      fps: parsed.fps,
      pointsInWindow: parsed.points_in_window,
      latencyMs: parsed.latency_ms,
    };
  }

  const view = new DataView(data);
  const msgType = view.getUint32(0, true);

  if (msgType === SCAN_WS_TYPE) {
    const pointCount = view.getUint32(4, true);
    const points = new Float32Array(data, 8, pointCount * 4);
    return { type: 'scan', points, pointCount };
  }

  if (msgType === IMU_WS_TYPE) {
    const floats = new Float32Array(data, 4, 10);
    return {
      type: 'imu',
      quaternion: floats.subarray(0, 4),
      angularVelocity: floats.subarray(4, 7),
      linearAcceleration: floats.subarray(7, 10),
    };
  }

  if (msgType === OBSTACLES_WS_TYPE) {
    const clusterCount = view.getUint32(4, true);
    const clusters = [];
    const recordBytes = OBSTACLE_RECORD_FLOATS * 4;
    for (let i = 0; i < clusterCount; i++) {
      const f = new Float32Array(data, 8 + i * recordBytes, OBSTACLE_RECORD_FLOATS);
      clusters.push({
        xMin: f[0], xMax: f[1],
        yMin: f[2], yMax: f[3],
        zMin: f[4], zMax: f[5],
        centroidX: f[6], centroidY: f[7], centroidZ: f[8],
        pointCount: f[9],
        meanIntensity: f[10],
        anomalyScore: f[11],
      });
    }
    return { type: 'obstacles', clusters };
  }

  throw new Error(`nieznany typ wiadomosci WS: ${msgType}`);
}

function connect(url, { onScan, onImu, onMetrics, onObstacles, onDisconnect }) {
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.addEventListener('message', (event) => {
    let decoded;
    try {
      decoded = decodeMessage(event.data);
    } catch (err) {
      // Pojedyncza uszkodzona/nieznana ramka nie moze zabic handlera -
      // bez tego catch reszta strumienia przestawala byc przetwarzana po
      // cichu, a strona wygladala jakby dzialala.
      console.warn('pominieto nieczytelna ramke WS:', err);
      return;
    }
    if (decoded.type === 'scan') onScan(decoded);
    else if (decoded.type === 'imu') onImu(decoded);
    else if (decoded.type === 'metrics') onMetrics(decoded);
    else if (decoded.type === 'obstacles' && onObstacles) onObstacles(decoded);
  });

  // Bez tych dwoch handlerow kazdy tryb awarii (serwer padl, koniec
  // nagrania, zly URL, martwy bridge) wygladal identycznie: zamrozona
  // strona ze stara chmura punktow. Spec tego zabrania wprost.
  ws.addEventListener('close', (event) => {
    if (onDisconnect) {
      onDisconnect({ reason: 'close', code: event.code, wasClean: event.wasClean });
    }
  });

  ws.addEventListener('error', () => {
    if (onDisconnect) onDisconnect({ reason: 'error' });
  });

  return ws;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { decodeMessage, connect, SCAN_WS_TYPE, IMU_WS_TYPE, OBSTACLES_WS_TYPE };
} else {
  window.wsClient = { decodeMessage, connect, SCAN_WS_TYPE, IMU_WS_TYPE, OBSTACLES_WS_TYPE };
}
