// =============================================================================
// Zakladka LiDAR - struktura pliku:
//   1. Macierze (perspektywa/widok/obrot) - czysta matematyka, bez WebGL.
//   2. Dane chmury punktow -> bufory WebGL (pozycja, kolor wg odbicia).
//   3. initLidarTab(context) - caly stan i UI zakladki:
//      3.1 DOM + inicjalizacja WebGL (shadery, program, atrybuty/uniformy)
//      3.2 Kamera orbitalna (mysz/dotyk)
//      3.3 Chmura punktow LiDAR (bufor + rysowanie)
//      3.4 Korekta obrotu montazu czujnika (uzywana przez modul zagrozen i SLAM)
//      3.5 MODUL ZAGROZEN: siatka zajetosci + predykcja + linia ostrzegawcza
//          + planowanie trasy (A*) - to jest "sekcja lidar" wymieniona w
//          historii zmian: wczesniej rozrzucona po calym pliku, teraz w
//          jednym miejscu (stan, przeliczanie po skanie, rysowanie, UI).
//      3.6 MODUL SLAM: dopasowanie skanow (ICP) + akumulowana mapa/trasa.
//      3.7 Petla render() - rysuje chmure + nakladke zagrozen + SLAM.
//      3.8 Odbior danych z serwera (context.onControlMessage).
//      3.9 Pozostale UI: start/stop streamu, obrot/reset/zoom widoku.
// =============================================================================

// --- 1. Macierze ------------------------------------------------------------

function perspectiveMat4(fovy, aspect, near, far) {
  const f = 1.0 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, 2 * far * near * nf, 0,
  ]);
}

function lookAtMat4(eye, center, up) {
  const [ex, ey, ez] = eye;
  const [cx, cy, cz] = center;

  let zx = ex - cx, zy = ey - cy, zz = ez - cz;
  let len = Math.hypot(zx, zy, zz) || 1;
  zx /= len; zy /= len; zz /= len;

  let xx = up[1] * zz - up[2] * zy;
  let xy = up[2] * zx - up[0] * zz;
  let xz = up[0] * zy - up[1] * zx;
  len = Math.hypot(xx, xy, xz) || 1;
  xx /= len; xy /= len; xz /= len;

  const yx = zy * xz - zz * xy;
  const yy = zz * xx - zx * xz;
  const yz = zx * xy - zy * xx;

  return new Float32Array([
    xx, yx, zx, 0,
    xy, yy, zy, 0,
    xz, yz, zz, 0,
    -(xx * ex + xy * ey + xz * ez),
    -(yx * ex + yy * ey + yz * ez),
    -(zx * ex + zy * ey + zz * ez),
    1,
  ]);
}

function rotateXMat4(rad) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float32Array([
    1, 0, 0, 0,
    0, c, s, 0,
    0, -s, c, 0,
    0, 0, 0, 1,
  ]);
}

function rotateYMat4(rad) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float32Array([
    c, 0, -s, 0,
    0, 1, 0, 0,
    s, 0, c, 0,
    0, 0, 0, 1,
  ]);
}

function rotateZMat4(rad) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float32Array([
    c, s, 0, 0,
    -s, c, 0, 0,
    0, 0, 1, 0,
    0, 0, 0, 1,
  ]);
}

// b * a (kolejnosc jak przy mnozeniu macierzy transformacji: najpierw a, potem b)
function multiplyMat4(b, a) {
  const out = new Float32Array(16);
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) {
        sum += b[k * 4 + row] * a[col * 4 + k];
      }
      out[col * 4 + row] = sum;
    }
  }
  return out;
}

// --- 2. Dane chmury punktow -> bufory WebGL ---------------------------------

// Punkty z lidaru przychodza jako {x, y, z, intensity, color} gdzie
// y = do przodu, z = w gore. Na potrzeby renderowania (Y w gore, Z w strone
// kamery) zamieniamy osie.
function lidarPointsToRenderBuffer(points) {
  const flat = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    flat[i * 3] = p.x;
    flat[i * 3 + 1] = p.z;
    flat[i * 3 + 2] = p.y;
  }
  return flat;
}

// "#rrggbb" -> [r, g, b] w zakresie 0-1. Brak/zly format -> szary (fallback).
function hexColorToRgb(hex) {
  if (typeof hex !== 'string' || hex.length !== 7 || hex[0] !== '#') {
    return [0.7, 0.7, 0.7];
  }
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) {
    return [0.7, 0.7, 0.7];
  }
  return [r / 255, g / 255, b / 255];
}

// Kolor punktu z lidaru wg sily odbicia (server juz przysyla gotowy kolor w
// polu "color" - patrz _reflectivity_to_color w command_processor.py:
// czerwony = slabe odbicie/przeszkoda, niebieski = silne odbicie).
function lidarPointsToColorBuffer(points) {
  const flat = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    const [r, g, b] = hexColorToRgb(points[i].color);
    flat[i * 3] = r;
    flat[i * 3 + 1] = g;
    flat[i * 3 + 2] = b;
  }
  return flat;
}

// Lidar jest fizycznie zamontowany na boku (obrocony wokol osi "do przodu"),
// wiec domyslnie doliczamy korekte 90 stopni rolu (obrot wokol osi Z w
// przestrzeni renderowania), zeby "gora" czujnika odpowiadala prawdziwej
// pionowej osi robota.
const DEFAULT_ROTATION_DEG = { x: 0, y: 0, z: 90 };

const IDENTITY_MAT4 = new Float32Array([
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
]);

function initLidarTab(context) {
  // --- 3.1 DOM + inicjalizacja WebGL -----------------------------------------
  const canvas = document.getElementById('lidar-canvas');
  const countEl = document.getElementById('lidar-point-count');
  const startBtn = document.getElementById('lidar-start');
  const stopBtn = document.getElementById('lidar-stop');
  const rotateXBtn = document.getElementById('lidar-rotate-x');
  const rotateYBtn = document.getElementById('lidar-rotate-y');
  const rotateZBtn = document.getElementById('lidar-rotate-z');
  const resetRotationBtn = document.getElementById('lidar-reset-rotation');
  const resetViewBtn = document.getElementById('lidar-reset-view');
  const zoomInBtn = document.getElementById('lidar-zoom-in');
  const zoomOutBtn = document.getElementById('lidar-zoom-out');
  const rotationLabel = document.getElementById('lidar-rotation-label');
  if (!canvas) return;

  const gl = canvas.getContext('webgl');
  if (!gl) {
    if (countEl) countEl.textContent = 'WebGL niedostępny';
    return;
  }

  const vsSource = `
    attribute vec3 aPosition;
    attribute vec3 aColor;
    uniform mat4 uProjection;
    uniform mat4 uView;
    uniform mat4 uModel;
    uniform float uPointSize;
    varying float vDistance;
    varying vec3 vColor;
    void main() {
      vec4 worldPos = uModel * vec4(aPosition, 1.0);
      gl_Position = uProjection * uView * worldPos;
      gl_PointSize = uPointSize;
      vDistance = length(worldPos.xyz);
      vColor = aColor;
    }
  `;
  const fsSource = `
    precision mediump float;
    varying float vDistance;
    varying vec3 vColor;
    uniform float uMaxDistance;
    uniform bool uUseOverride;
    uniform vec4 uOverrideColor;
    uniform bool uUseVertexColor;
    void main() {
      if (uUseVertexColor) {
        gl_FragColor = vec4(vColor, 1.0);
        return;
      }
      if (uUseOverride) {
        gl_FragColor = uOverrideColor;
        return;
      }
      float t = clamp(vDistance / max(uMaxDistance, 0.001), 0.0, 1.0);
      // blisko = zielono-niebieski, daleko = zolto-czerwony
      vec3 near = vec3(0.15, 0.75, 0.6);
      vec3 mid = vec3(0.95, 0.8, 0.2);
      vec3 far = vec3(0.9, 0.2, 0.2);
      vec3 color = t < 0.5
        ? mix(near, mid, t / 0.5)
        : mix(mid, far, (t - 0.5) / 0.5);
      gl_FragColor = vec4(color, 1.0);
    }
  `;

  function compileShader(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error('Lidar shader error:', gl.getShaderInfoLog(shader));
    }
    return shader;
  }

  const program = gl.createProgram();
  gl.attachShader(program, compileShader(gl.VERTEX_SHADER, vsSource));
  gl.attachShader(program, compileShader(gl.FRAGMENT_SHADER, fsSource));
  gl.linkProgram(program);
  gl.useProgram(program);

  const aPosition = gl.getAttribLocation(program, 'aPosition');
  const aColor = gl.getAttribLocation(program, 'aColor');
  const uProjection = gl.getUniformLocation(program, 'uProjection');
  const uView = gl.getUniformLocation(program, 'uView');
  const uModel = gl.getUniformLocation(program, 'uModel');
  const uMaxDistance = gl.getUniformLocation(program, 'uMaxDistance');
  const uPointSize = gl.getUniformLocation(program, 'uPointSize');
  const uUseOverride = gl.getUniformLocation(program, 'uUseOverride');
  const uOverrideColor = gl.getUniformLocation(program, 'uOverrideColor');
  const uUseVertexColor = gl.getUniformLocation(program, 'uUseVertexColor');
  gl.vertexAttrib3f(aColor, 1.0, 1.0, 1.0);

  // --- 3.2 Kamera orbitalna (przeciaganie = obrot, scroll/przyciski = zoom) --
  const DEFAULT_CAMERA = { yaw: 0.8, pitch: -0.4, distance: 8 };
  const camera = { ...DEFAULT_CAMERA };
  const MIN_DISTANCE = 0.5;
  const MAX_DISTANCE = 60;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  function zoomBy(factor) {
    camera.distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, camera.distance * factor));
  }

  canvas.addEventListener('mousedown', (e) => {
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
  });
  window.addEventListener('mouseup', () => {
    dragging = false;
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    camera.yaw += dx * 0.005;
    camera.pitch = Math.max(-1.5, Math.min(1.5, camera.pitch - dy * 0.005));
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomBy(1 + e.deltaY * 0.001);
  }, { passive: false });

  // dwa palce: pierwszy = obrot, odleglosc miedzy palcami = zoom (pinch)
  let lastTouch = null;
  let lastPinchDist = null;

  function touchDist(touches) {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.hypot(dx, dy);
  }

  canvas.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      lastTouch = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      lastPinchDist = null;
    } else if (e.touches.length === 2) {
      lastPinchDist = touchDist(e.touches);
      lastTouch = null;
    }
  });
  canvas.addEventListener('touchmove', (e) => {
    if (e.touches.length === 1 && lastTouch) {
      const dx = e.touches[0].clientX - lastTouch.x;
      const dy = e.touches[0].clientY - lastTouch.y;
      lastTouch = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      camera.yaw += dx * 0.005;
      camera.pitch = Math.max(-1.5, Math.min(1.5, camera.pitch - dy * 0.005));
      e.preventDefault();
    } else if (e.touches.length === 2 && lastPinchDist) {
      const dist = touchDist(e.touches);
      zoomBy(lastPinchDist / Math.max(dist, 1));
      lastPinchDist = dist;
      e.preventDefault();
    }
  }, { passive: false });
  canvas.addEventListener('touchend', (e) => {
    if (e.touches.length === 0) {
      lastTouch = null;
      lastPinchDist = null;
    }
  });

  function resizeIfNeeded() {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
    }
  }

  // --- 3.3 Chmura punktow LiDAR (bufor + rysowanie) --------------------------
  const vertexBuffer = gl.createBuffer();
  const colorBuffer = gl.createBuffer();
  let pointCount = 0;
  let maxDistance = 1.0;

  function setPoints(points) {
    const flat = lidarPointsToRenderBuffer(points);
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);

    const colorFlat = lidarPointsToColorBuffer(points);
    gl.bindBuffer(gl.ARRAY_BUFFER, colorBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, colorFlat, gl.DYNAMIC_DRAW);

    pointCount = points.length;
    if (countEl) countEl.textContent = `${pointCount} punktów`;

    let maxSq = 0;
    for (let i = 0; i < points.length; i++) {
      const x = flat[i * 3], y = flat[i * 3 + 1], z = flat[i * 3 + 2];
      const distSq = x * x + y * y + z * z;
      if (distSq > maxSq) maxSq = distSq;
    }
    maxDistance = points.length > 0 ? Math.sqrt(maxSq) : 1.0;
  }

  // --- siatka odniesienia (podloga) + osie XYZ ---------------------------
  // Staly punkt odniesienia do oceny skali/orientacji chmury - bez tego
  // punkty "wisza" w pustej czerni bez zadnego odniesienia do rzeczywistych
  // odleglosci. Rysowane w tej samej (skorygowanej) przestrzeni co nakladka
  // modulu zagrozen (IDENTITY_MAT4), wiec siatka reprezentuje realna
  // poziomu podloge robota, niezaleznie od obrotu rotationDeg chmury.
  const REFERENCE_GRID_EXTENT_M = 6; // +-6m od robota
  const REFERENCE_GRID_STEP_M = 1;   // linia co 1m
  const AXIS_LENGTH_M = 1.0;

  function buildReferenceGridVertices() {
    const lines = [];
    for (let i = -REFERENCE_GRID_EXTENT_M; i <= REFERENCE_GRID_EXTENT_M; i += REFERENCE_GRID_STEP_M) {
      lines.push(-REFERENCE_GRID_EXTENT_M, 0, i, REFERENCE_GRID_EXTENT_M, 0, i);
      lines.push(i, 0, -REFERENCE_GRID_EXTENT_M, i, 0, REFERENCE_GRID_EXTENT_M);
    }
    return new Float32Array(lines);
  }

  const referenceGridBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, referenceGridBuffer);
  const referenceGridVertices = buildReferenceGridVertices();
  gl.bufferData(gl.ARRAY_BUFFER, referenceGridVertices, gl.STATIC_DRAW);
  const referenceGridVertexCount = referenceGridVertices.length / 3;

  // Osie: X (prawo, czerwony), Y (gora, zielony), Z (przod, niebieski).
  const axesBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, axesBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    0, 0, 0, AXIS_LENGTH_M, 0, 0,
    0, 0, 0, 0, AXIS_LENGTH_M, 0,
    0, 0, 0, 0, 0, AXIS_LENGTH_M,
  ]), gl.STATIC_DRAW);

  // --- 3.4 Korekta obrotu montazu czujnika ------------------------------------
  // Obrot calej chmury punktow, niezalezny od kamery. Kazda os liczona
  // osobno i pokazywana w etykiecie, zeby latwo bylo trafic w 90/180/270.
  const rotationDeg = { ...DEFAULT_ROTATION_DEG };

  function updateRotationLabel() {
    if (rotationLabel) {
      rotationLabel.textContent = `obrót X:${rotationDeg.x}° Y:${rotationDeg.y}° Z:${rotationDeg.z}°`;
    }
  }
  updateRotationLabel();

  // Przeksztalca surowy punkt LiDAR [x, y, z] (y=przod, z=gora w ramce
  // czujnika) do tej samej finalnej przestrzeni, w ktorej faktycznie
  // wyswietlana jest chmura punktow (czyli po zamianie osi jak w
  // lidarPointsToRenderBuffer ORAZ po korekcie obrotu rotationDeg - lidar
  // jest fizycznie zamontowany na boku, wiec bez tej korekty modul zagrozen
  // (siatka, wysokosc) i SLAM ladowalyby w zla os i wychodzily obrocone
  // wzgledem rzeczywiscie wyswietlanej chmury punktow).
  function correctLidarPoint(p) {
    const rad = (deg) => (deg * Math.PI) / 180;
    let x = p.x;
    let y = p.z;
    let z = p.y;

    {
      const c = Math.cos(rad(rotationDeg.x));
      const s = Math.sin(rad(rotationDeg.x));
      const ny = c * y - s * z;
      const nz = s * y + c * z;
      y = ny; z = nz;
    }
    {
      const c = Math.cos(rad(rotationDeg.y));
      const s = Math.sin(rad(rotationDeg.y));
      const nx = c * x + s * z;
      const nz = -s * x + c * z;
      x = nx; z = nz;
    }
    {
      const c = Math.cos(rad(rotationDeg.z));
      const s = Math.sin(rad(rotationDeg.z));
      const nx = c * x - s * y;
      const ny = s * x + c * y;
      x = nx; y = ny;
    }

    return { x, y, z }; // x=prawo, y=gora (po korekcie), z=przod
  }

  // =========================================================================
  // 3.5 MODUL ZAGROZEN: siatka zajetosci + predykcja + linia ostrzegawcza
  // + planowanie trasy (A*). Caly stan i logika tej funkcji jest tutaj, w
  // jednym miejscu - poprzednio bylo rozrzucone po calym pliku (deklaracje
  // przy komentarzu "nakladka AI", funkcje przeliczajace bufory w srodku
  // pliku, aktualizacja po skanie w handlerze wiadomosci, a UI/A* na samym
  // koncu przy przyciskach).
  // =========================================================================

  // Float, nie Uint8: hits zanika w czasie (patrz AI_HIT_DECAY) zamiast
  // rosnac w nieskonczonosc - bez tego kazda komorka w zasiegu czujnika
  // wczesniej czy pozniej dostaje >=2 trafienia (szum, wielodrozność) i
  // zostaje trwale oznaczona jako przeszkoda, co daje lity blok w ksztalcie
  // calego zasiegu sensora zamiast realnych przeszkod.
  const hits = new Float32Array(AI_GRID_SIZE * AI_GRID_SIZE);
  const AI_HIT_DECAY = 0.6; // na kazdy cykl odswiezania mapy (~500ms)
  // Predykcja: wynik ekstrapolacji trendu hits (patrz aiPredictOccupancy w ai.js).
  let predictedHits = new Float32Array(AI_GRID_SIZE * AI_GRID_SIZE);
  // Najwyzsza skorygowana wysokosc (metry nad "podloga" filtra) zaobserwowana
  // w danej komorce - uzywana do rysowania przeszkod jako slupkow, a nie
  // plaskich punktow, zeby mapa niosla realna informacje 3D o wysokosci.
  const heights = new Float32Array(AI_GRID_SIZE * AI_GRID_SIZE);
  const MAX_COLUMN_HEIGHT = 2.5; // metry, tylko zabezpieczenie renderowania

  let aiTarget = null;
  let aiPath = null;
  let aiPollTimer = null;
  let aiRunning = false;

  const gridBuffer = gl.createBuffer();
  let gridColumnCount = 0;
  const predictedGridBuffer = gl.createBuffer();
  let predictedCellCount = 0;
  const pathBuffer = gl.createBuffer();
  let pathPointCount = 0;
  const markerBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, markerBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 0]), gl.STATIC_DRAW);
  const targetBuffer = gl.createBuffer();
  let hasTarget = false;

  // Komorka siatki (raw x,y z danych LiDAR, z=0) -> ta sama konwencja co
  // lidarPointsToRenderBuffer: render (x, z, y).
  function gridCellToRenderPoint(gx, gy) {
    const world = aiGridToWorld(gx, gy);
    return [world.x, 0, world.y];
  }

  // Kazda zajeta komorka to teraz slupek: wierzcholek "podloga" (y=0) i
  // wierzcholek "szczyt" (y=wysokosc), naprzemiennie w tym samym buforze -
  // dzieki temu mozna go narysowac jako LINES (pionowe kreski) i osobnym
  // odczytem (ze stride/offset) jako POINTS tylko dla wierzcholkow szczytu.
  function rebuildGridBuffer() {
    const cells = [];
    for (let gy = 0; gy < AI_GRID_SIZE; gy++) {
      for (let gx = 0; gx < AI_GRID_SIZE; gx++) {
        const idx = gy * AI_GRID_SIZE + gx;
        if (hits[idx] >= AI_HIT_THRESHOLD) {
          cells.push([gx, gy, idx]);
        }
      }
    }
    const flat = new Float32Array(cells.length * 6);
    cells.forEach(([gx, gy, idx], i) => {
      const [x, , z] = gridCellToRenderPoint(gx, gy);
      const h = Math.max(0, Math.min(MAX_COLUMN_HEIGHT, heights[idx]));
      flat[i * 6] = x;
      flat[i * 6 + 1] = 0;
      flat[i * 6 + 2] = z;
      flat[i * 6 + 3] = x;
      flat[i * 6 + 4] = h;
      flat[i * 6 + 5] = z;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, gridBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
    gridColumnCount = cells.length;
  }

  // Komorki, ktore trend wskazuje jako "zaraz przeszkoda" (predictedHits >=
  // prog), ale jeszcze nie sa realna przeszkoda (hits < prog) - to jest
  // rysowane osobno jako ostrzeganie na wyprzedzenie.
  function rebuildPredictedGridBuffer() {
    const cells = [];
    for (let gy = 0; gy < AI_GRID_SIZE; gy++) {
      for (let gx = 0; gx < AI_GRID_SIZE; gx++) {
        const idx = gy * AI_GRID_SIZE + gx;
        if (hits[idx] < AI_HIT_THRESHOLD && predictedHits[idx] >= AI_HIT_THRESHOLD) {
          cells.push([gx, gy]);
        }
      }
    }
    const flat = new Float32Array(cells.length * 3);
    cells.forEach(([gx, gy], i) => {
      const [x, , z] = gridCellToRenderPoint(gx, gy);
      flat[i * 3] = x;
      flat[i * 3 + 1] = 0;
      flat[i * 3 + 2] = z;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, predictedGridBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
    predictedCellCount = cells.length;
  }

  function rebuildPathBuffer() {
    if (!aiPath || aiPath.length < 2) {
      pathPointCount = 0;
      return;
    }
    const flat = new Float32Array(aiPath.length * 3);
    aiPath.forEach((cell, i) => {
      const [x, y, z] = gridCellToRenderPoint(cell.gx, cell.gy);
      flat[i * 3] = x;
      flat[i * 3 + 1] = y;
      flat[i * 3 + 2] = z;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, pathBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
    pathPointCount = aiPath.length;
  }

  function rebuildTargetBuffer() {
    hasTarget = !!aiTarget;
    if (!aiTarget) return;
    const [x, y, z] = gridCellToRenderPoint(aiTarget.gx, aiTarget.gy);
    gl.bindBuffer(gl.ARRAY_BUFFER, targetBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([x, y, z]), gl.DYNAMIC_DRAW);
  }

  const aiStatusEl = document.getElementById('ai-status');
  const aiStartBtn = document.getElementById('ai-map-start');
  const aiStopBtn = document.getElementById('ai-map-stop');
  const aiClearBtn = document.getElementById('ai-map-clear');
  const aiTargetXInput = document.getElementById('ai-target-x');
  const aiTargetYInput = document.getElementById('ai-target-y');
  const aiTargetSetBtn = document.getElementById('ai-target-set');
  const aiRunBtn = document.getElementById('ai-run-path');
  const aiHeightMinInput = document.getElementById('ai-height-min');
  const aiHeightMaxInput = document.getElementById('ai-height-max');

  function setAiStatus(text) {
    if (aiStatusEl) aiStatusEl.textContent = text;
  }

  function recomputeAiPath() {
    aiPath = aiFindPath(hits, { gx: AI_ORIGIN, gy: AI_ORIGIN }, aiTarget, predictedHits);
    rebuildPathBuffer();
    if (!aiPath) {
      setAiStatus('Brak trasy do celu (zablokowana przez przeszkody, w tym przewidywane)');
    } else {
      const steps = aiPathToSteps(aiPath);
      const opis = steps.map((s) => `${s.direction}×${s.cells}`).join(', ');
      setAiStatus(`Trasa: ${aiPath.length} komórek — ${opis} (przewidywane przeszkody: ${predictedCellCount})`);
    }
  }

  // Przelicza siatke zagrozen na podstawie jednego przychodzacego skanu -
  // wywolywane przy kazdej odebranej chmurze punktow (patrz 3.8), niezaleznie
  // od tego, czy ktos klikal "Start" w panelu AI (ten przycisk wlacza tylko
  // dodatkowe planowanie trasy A* do zadanego celu).
  function updateThreatGrid(points) {
    // Migawka hits sprzed tego skanu - potrzebna do policzenia trendu
    // (przyrost/zanik trafien miedzy skanami) na potrzeby predykcji ponizej.
    const prevHitsSnapshot = hits.slice();

    // Zanik przed doliczeniem nowych trafien - tylko komorki widziane
    // konsekwentnie w kolejnych skanach zostaja oznaczone jako przeszkoda,
    // pojedyncze/szumowe trafienia szybko wygasaja.
    for (let i = 0; i < hits.length; i++) {
      hits[i] *= AI_HIT_DECAY;
      if (hits[i] < 0.05) {
        hits[i] = 0;
        heights[i] = 0;
      }
    }

    const zMin = Number(aiHeightMinInput ? aiHeightMinInput.value : 0.05);
    const zMax = Number(aiHeightMaxInput ? aiHeightMaxInput.value : 0.6);
    // Jeden skan LiDAR-u ma dziesiatki tysiecy punktow - bez tego kazda
    // komorka blisko robota dostawalaby dziesiatki trafien W JEDNYM skanie
    // i przebijala prog zanim zanik miedzy skanami zdazyl cokolwiek zrobic.
    // Liczymy wiec najwyzej +1 do komorki na skan (= "widziane w tym
    // skanie"), a nie +1 za kazdy pojedynczy punkt.
    const touchedThisScan = new Set();
    for (const p of points) {
      // Uzywamy punktu w tej samej, skorygowanej przestrzeni co wyswietlana
      // chmura (patrz correctLidarPoint) - inaczej siatka i filtr wysokosci
      // ladowaly w surowa, nieobrocona ramke czujnika i wychodzily obrocone
      // wzgledem tego, co faktycznie widac na scenie 3D.
      const c = correctLidarPoint(p);
      if (c.y < zMin || c.y > zMax) continue;

      const { gx, gy } = aiWorldToGrid(c.x, c.z);
      if (!aiInBounds(gx, gy)) continue;
      const idx = gy * AI_GRID_SIZE + gx;
      if (!touchedThisScan.has(idx)) {
        touchedThisScan.add(idx);
        hits[idx] += 1;
      }
      // wysokosc slupka = jak wysoko nad "podloga" filtra siega przeszkoda
      const columnHeight = c.y - zMin;
      if (columnHeight > heights[idx]) heights[idx] = columnHeight;
    }

    predictedHits = aiPredictOccupancy(hits, prevHitsSnapshot);

    rebuildGridBuffer();
    rebuildPredictedGridBuffer();

    if (aiTarget) {
      recomputeAiPath();
    } else {
      setAiStatus(
        gridColumnCount > 0
          ? `Wykryto przeszkody: ${gridColumnCount} komórek (przewidywane: ${predictedCellCount})`
          : 'Brak wykrytych przeszkód w zasięgu'
      );
    }
  }

  function resetThreatGrid() {
    hits.fill(0);
    heights.fill(0);
    predictedHits.fill(0);
    aiTarget = null;
    aiPath = null;
    rebuildGridBuffer();
    rebuildPredictedGridBuffer();
    rebuildPathBuffer();
    rebuildTargetBuffer();
  }

  if (aiStartBtn) {
    aiStartBtn.addEventListener('click', () => {
      if (aiPollTimer) return;
      context.sendControl({ type: 'get_lidar_points' });
      aiPollTimer = setInterval(() => {
        context.sendControl({ type: 'get_lidar_points' });
      }, 500);
      setAiStatus('Mapowanie aktywne…');
    });
  }

  if (aiStopBtn) {
    aiStopBtn.addEventListener('click', () => {
      if (aiPollTimer) {
        clearInterval(aiPollTimer);
        aiPollTimer = null;
      }
      setAiStatus('Mapowanie zatrzymane');
    });
  }

  if (aiClearBtn) {
    aiClearBtn.addEventListener('click', () => {
      resetThreatGrid();
      setAiStatus('Mapa wyczyszczona');
    });
  }

  if (aiTargetSetBtn) {
    aiTargetSetBtn.addEventListener('click', () => {
      const x = Number(aiTargetXInput ? aiTargetXInput.value : 0) || 0;
      const y = Number(aiTargetYInput ? aiTargetYInput.value : 0) || 0;
      aiTarget = aiWorldToGrid(x, y);
      rebuildTargetBuffer();
      recomputeAiPath();
    });
  }

  if (aiRunBtn) {
    aiRunBtn.addEventListener('click', async () => {
      if (!aiPath || aiRunning) return;
      aiRunning = true;
      aiRunBtn.disabled = true;
      setAiStatus('Wykonywanie trasy (open-loop)…');

      const steps = aiPathToSteps(aiPath);
      const MS_PER_CELL = 350;
      const pwm = 1500;

      for (const step of steps) {
        const values = computeChannelValues(new Set([step.direction]), pwm);
        for (let channel = 0; channel < 8; channel++) {
          context.sendControl({ type: 'motor', channel, pwm: values[channel] });
        }
        await new Promise((resolve) => setTimeout(resolve, step.cells * MS_PER_CELL));
      }

      const zero = computeChannelValues(new Set(), pwm);
      for (let channel = 0; channel < 8; channel++) {
        context.sendControl({ type: 'motor', channel, pwm: zero[channel] });
      }

      aiRunning = false;
      aiRunBtn.disabled = false;
      setAiStatus('Trasa wykonana');
    });
  }

  // =========================================================================
  // 3.6 MODUL SLAM: dopasowanie skanow (scan-to-map ICP w plaszczyznie x/z)
  // do estymacji ruchu robota + akumulacja globalnej, kolorowanej mapy i
  // trasy. Osobna warstwa od modulu zagrozen powyzej - patrz komentarz w UI.
  // =========================================================================
  let slamActive = false;
  let slamPose = { theta: 0, tx: 0, tz: 0 };
  let slamMatchMap = []; // {x,z} - rzadka, do ICP
  let slamDisplayPoints = []; // {x,y,z,r,g,b} - gestsza, do renderu
  let slamTrajectory = []; // {x,z}
  const SLAM_MATCH_VOXEL = 0.1;
  const SLAM_MATCH_MAP_CAP = 4000;
  const SLAM_DISPLAY_CAP = 45000;
  const SLAM_MAX_HEIGHT_FOR_COLOR = 2.0;

  const slamMapBuffer = gl.createBuffer();
  let slamMapPointCount = 0;
  const slamTrajectoryBuffer = gl.createBuffer();
  let slamTrajectoryPointCount = 0;
  const slamRobotBuffer = gl.createBuffer();
  const slamHeadingBuffer = gl.createBuffer();

  function heightToColor(y) {
    const t = Math.max(0, Math.min(1, y / SLAM_MAX_HEIGHT_FOR_COLOR));
    const near = [0.15, 0.75, 0.6];
    const mid = [0.95, 0.8, 0.2];
    const far = [0.9, 0.2, 0.2];
    const from = t < 0.5 ? near : mid;
    const to = t < 0.5 ? mid : far;
    const localT = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
    return [
      from[0] + (to[0] - from[0]) * localT,
      from[1] + (to[1] - from[1]) * localT,
      from[2] + (to[2] - from[2]) * localT,
    ];
  }

  function rebuildSlamMapBuffer() {
    const flat = new Float32Array(slamDisplayPoints.length * 6);
    slamDisplayPoints.forEach((p, i) => {
      flat[i * 6] = p.x;
      flat[i * 6 + 1] = p.y;
      flat[i * 6 + 2] = p.z;
      flat[i * 6 + 3] = p.r;
      flat[i * 6 + 4] = p.g;
      flat[i * 6 + 5] = p.b;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, slamMapBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
    slamMapPointCount = slamDisplayPoints.length;
  }

  function rebuildSlamTrajectoryBuffer() {
    const flat = new Float32Array(slamTrajectory.length * 3);
    slamTrajectory.forEach((p, i) => {
      flat[i * 3] = p.x;
      flat[i * 3 + 1] = 0.02; // odrobine nad podloga, zeby nie znikala w Z-fight
      flat[i * 3 + 2] = p.z;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, slamTrajectoryBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
    slamTrajectoryPointCount = slamTrajectory.length;
  }

  function rebuildSlamRobotBuffers() {
    gl.bindBuffer(gl.ARRAY_BUFFER, slamRobotBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([slamPose.tx, 0.02, slamPose.tz]), gl.DYNAMIC_DRAW);

    const headingLen = 0.35;
    const hx = slamPose.tx + Math.sin(slamPose.theta) * headingLen;
    const hz = slamPose.tz + Math.cos(slamPose.theta) * headingLen;
    gl.bindBuffer(gl.ARRAY_BUFFER, slamHeadingBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([slamPose.tx, 0.02, slamPose.tz, hx, 0.02, hz]),
      gl.DYNAMIC_DRAW,
    );
  }

  function resetSlam() {
    slamPose = { theta: 0, tx: 0, tz: 0 };
    slamMatchMap = [];
    slamDisplayPoints = [];
    slamTrajectory = [];
    rebuildSlamMapBuffer();
    rebuildSlamTrajectoryBuffer();
    rebuildSlamRobotBuffers();
  }
  resetSlam();

  // Przetwarza jeden przychodzacy skan LiDAR-u (juz po korekcie obrotu z
  // correctLidarPoint) dla SLAM-u: dopasowuje go do dotychczasowej mapy
  // (scan-to-map ICP), aktualizuje pozycje robota i dolewa punkty do map.
  function processSlamScan(correctedPoints) {
    const matchCandidates = correctedPoints.map((c) => ({ x: c.x, z: c.z }));
    const localScanDown = voxelDownsample2D(matchCandidates, SLAM_MATCH_VOXEL);
    let statusMessage = null;

    if (slamMatchMap.length === 0) {
      // pierwszy skan od "Start SLAM" - definiuje uklad wspolrzednych swiata
      slamMatchMap = localScanDown;
      slamTrajectory.push({ x: 0, z: 0 });
    } else {
      const guessPoints = localScanDown.map((p) => applyPose2D(slamPose, p));
      const correction = icp2d(guessPoints, slamMatchMap, {
        maxCorrespondenceDist: 0.35,
        maxIterations: 15,
      });

      if (correction.iterations === 0 || correction.meanError > 0.3) {
        // za slabe dopasowanie (za malo wspolnych punktow / za duzy blad) -
        // pomijamy ten skan zamiast psuc mape zlym poprawieniem pozycji.
        statusMessage = `Dopasowanie nieudane (błąd ${correction.meanError.toFixed(2)}m) — pomijam skan`;
      } else {
        slamPose = composePose2D(correction, slamPose);
        const worldScan = localScanDown.map((p) => applyPose2D(slamPose, p));
        slamMatchMap = slamMatchMap.concat(worldScan);
        if (slamMatchMap.length > SLAM_MATCH_MAP_CAP) {
          slamMatchMap = voxelDownsample2D(slamMatchMap, SLAM_MATCH_VOXEL * 1.5);
        }
        slamTrajectory.push({ x: slamPose.tx, z: slamPose.tz });
      }
    }

    // Punkty do wyswietlenia (pelniejsza chmura, kolorowana wg wysokosci) -
    // ograniczone liczbowo, zeby WebGL i pamiec przegladarki nie ucierpialy.
    const step = Math.max(1, Math.floor(correctedPoints.length / 1500));
    for (let i = 0; i < correctedPoints.length; i += step) {
      const c = correctedPoints[i];
      const world = applyPose2D(slamPose, { x: c.x, z: c.z });
      const [r, g, b] = heightToColor(c.y);
      slamDisplayPoints.push({ x: world.x, y: Math.max(0, c.y), z: world.z, r, g, b });
    }
    if (slamDisplayPoints.length > SLAM_DISPLAY_CAP) {
      slamDisplayPoints.splice(0, slamDisplayPoints.length - SLAM_DISPLAY_CAP);
    }

    rebuildSlamMapBuffer();
    rebuildSlamTrajectoryBuffer();
    rebuildSlamRobotBuffers();

    if (!statusMessage) {
      statusMessage = `Pozycja: x=${slamPose.tx.toFixed(2)}m z=${slamPose.tz.toFixed(2)}m obrót=${((slamPose.theta * 180) / Math.PI).toFixed(1)}° — mapa: ${slamDisplayPoints.length} pkt`;
    }
    setSlamStatus(statusMessage);
  }

  const slamStatusEl = document.getElementById('slam-status');
  const slamStartBtn = document.getElementById('slam-start');
  const slamStopBtn = document.getElementById('slam-stop');
  const slamResetBtn = document.getElementById('slam-reset');
  let slamPollTimer = null;

  function setSlamStatus(text) {
    if (slamStatusEl) slamStatusEl.textContent = text;
  }

  if (slamStartBtn) {
    slamStartBtn.addEventListener('click', () => {
      slamActive = true;
      if (slamPollTimer) return;
      context.sendControl({ type: 'get_lidar_points' });
      slamPollTimer = setInterval(() => {
        context.sendControl({ type: 'get_lidar_points' });
      }, 500);
      setSlamStatus('SLAM aktywny…');
    });
  }

  if (slamStopBtn) {
    slamStopBtn.addEventListener('click', () => {
      slamActive = false;
      if (slamPollTimer) {
        clearInterval(slamPollTimer);
        slamPollTimer = null;
      }
      setSlamStatus('SLAM zatrzymany');
    });
  }

  if (slamResetBtn) {
    slamResetBtn.addEventListener('click', () => {
      resetSlam();
      setSlamStatus('SLAM zresetowany');
    });
  }

  // --- 3.7 Petla render() -----------------------------------------------------
  let rafId = null;

  function render() {
    resizeIfNeeded();
    gl.clearColor(0.05, 0.06, 0.09, 1.0);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const ex = camera.distance * Math.cos(camera.pitch) * Math.sin(camera.yaw);
    const ey = camera.distance * Math.sin(camera.pitch);
    const ez = camera.distance * Math.cos(camera.pitch) * Math.cos(camera.yaw);

    const view = lookAtMat4([ex, ey, ez], [0, 0, 0], [0, 1, 0]);
    const aspect = canvas.width / canvas.height || 1;
    const proj = perspectiveMat4(Math.PI / 3, aspect, 0.05, 300);

    let model = rotateXMat4((rotationDeg.x * Math.PI) / 180);
    model = multiplyMat4(rotateYMat4((rotationDeg.y * Math.PI) / 180), model);
    model = multiplyMat4(rotateZMat4((rotationDeg.z * Math.PI) / 180), model);

    gl.useProgram(program);
    gl.uniformMatrix4fv(uProjection, false, proj);
    gl.uniformMatrix4fv(uView, false, view);

    // --- siatka odniesienia (podloga) + osie XYZ - stabilny uklad swiata,
    // niezalezny od obrotu rotationDeg calej chmury, wiec IDENTITY_MAT4.
    gl.uniformMatrix4fv(uModel, false, IDENTITY_MAT4);
    gl.uniform1i(uUseOverride, 1);

    gl.uniform4f(uOverrideColor, 0.4, 0.45, 0.55, 0.25);
    gl.bindBuffer(gl.ARRAY_BUFFER, referenceGridBuffer);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.LINES, 0, referenceGridVertexCount);

    gl.bindBuffer(gl.ARRAY_BUFFER, axesBuffer);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.uniform4f(uOverrideColor, 0.9, 0.25, 0.25, 0.9); // X - prawo
    gl.drawArrays(gl.LINES, 0, 2);
    gl.uniform4f(uOverrideColor, 0.3, 0.85, 0.35, 0.9); // Y - gora
    gl.drawArrays(gl.LINES, 2, 2);
    gl.uniform4f(uOverrideColor, 0.3, 0.55, 0.95, 0.9); // Z - przod
    gl.drawArrays(gl.LINES, 4, 2);

    gl.uniformMatrix4fv(uModel, false, model);

    if (pointCount > 0) {
      // Kolor punktu wg sily odbicia (przyslany przez serwer), nie wg
      // odleglosci - patrz lidarPointsToColorBuffer / _reflectivity_to_color.
      gl.uniform1i(uUseOverride, 0);
      gl.uniform1i(uUseVertexColor, 1);
      gl.uniform1f(uPointSize, 3.0);
      gl.uniform1f(uMaxDistance, maxDistance);
      gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, colorBuffer);
      gl.enableVertexAttribArray(aColor);
      gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.POINTS, 0, pointCount);
      gl.disableVertexAttribArray(aColor);
      gl.uniform1i(uUseVertexColor, 0);
    }

    // --- nakladka modulu zagrozen: siatka, predykcja, linia, trasa, cel, robot ---
    // Te bufory sa juz zbudowane w finalnej (skorygowanej) przestrzeni -
    // patrz correctLidarPoint - wiec rysujemy je z macierza tozsamosci,
    // zeby nie nalozyc obrotu rotationDeg drugi raz.
    gl.uniformMatrix4fv(uModel, false, IDENTITY_MAT4);
    gl.uniform1i(uUseOverride, 1);

    if (gridColumnCount > 0) {
      // pionowe kreski slupka: podloga -> wykryta wysokosc przeszkody
      gl.uniform4f(uOverrideColor, 1.0, 0.3, 0.3, 0.5);
      gl.bindBuffer(gl.ARRAY_BUFFER, gridBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINES, 0, gridColumnCount * 2);

      // szczyty slupkow (co drugi wierzcholek w tym samym buforze)
      gl.uniform1f(uPointSize, 5.0);
      gl.uniform4f(uOverrideColor, 1.0, 0.45, 0.3, 0.85);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 6 * 4, 3 * 4);
      gl.drawArrays(gl.POINTS, 0, gridColumnCount);
    }

    if (predictedCellCount > 0) {
      // Komorki, ktore trend (aiPredictOccupancy) wskazuje jako "zaraz
      // przeszkoda" - pomaranczowe, plaskie punkty (jeszcze bez zmierzonej
      // wysokosci), odrozniajace sie od czerwonych realnych przeszkod.
      gl.uniform1f(uPointSize, 4.0);
      gl.uniform4f(uOverrideColor, 1.0, 0.65, 0.15, 0.55);
      gl.bindBuffer(gl.ARRAY_BUFFER, predictedGridBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.POINTS, 0, predictedCellCount);
    }

    if (pathPointCount > 1) {
      gl.uniform4f(uOverrideColor, 0.49, 0.49, 1.0, 0.95);
      gl.bindBuffer(gl.ARRAY_BUFFER, pathBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINE_STRIP, 0, pathPointCount);
    }

    if (hasTarget) {
      gl.uniform1f(uPointSize, 10.0);
      gl.uniform4f(uOverrideColor, 1.0, 0.83, 0.44, 1.0);
      gl.bindBuffer(gl.ARRAY_BUFFER, targetBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.POINTS, 0, 1);
    }

    gl.uniform1f(uPointSize, 9.0);
    gl.uniform4f(uOverrideColor, 0.37, 0.9, 0.63, 1.0);
    gl.bindBuffer(gl.ARRAY_BUFFER, markerBuffer);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.POINTS, 0, 1);

    // --- nakladka SLAM: zaakumulowana mapa (kolor wg wysokosci), trasa, pozycja ---
    if (slamMapPointCount > 0) {
      gl.uniform1i(uUseOverride, 0);
      gl.uniform1i(uUseVertexColor, 1);
      gl.uniform1f(uPointSize, 2.5);
      gl.bindBuffer(gl.ARRAY_BUFFER, slamMapBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 6 * 4, 0);
      gl.enableVertexAttribArray(aColor);
      gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, 6 * 4, 3 * 4);
      gl.drawArrays(gl.POINTS, 0, slamMapPointCount);
      gl.disableVertexAttribArray(aColor);
      gl.uniform1i(uUseVertexColor, 0);
      gl.uniform1i(uUseOverride, 1);
    }

    if (slamTrajectoryPointCount > 1) {
      gl.uniform4f(uOverrideColor, 0.95, 0.95, 0.95, 0.9);
      gl.bindBuffer(gl.ARRAY_BUFFER, slamTrajectoryBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINE_STRIP, 0, slamTrajectoryPointCount);
    }

    if (slamMapPointCount > 0 || slamTrajectoryPointCount > 0) {
      gl.uniform4f(uOverrideColor, 0.95, 0.95, 0.95, 0.9);
      gl.bindBuffer(gl.ARRAY_BUFFER, slamHeadingBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINES, 0, 2);

      gl.uniform1f(uPointSize, 10.0);
      gl.bindBuffer(gl.ARRAY_BUFFER, slamRobotBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.POINTS, 0, 1);
    }

    rafId = requestAnimationFrame(render);
  }

  rafId = requestAnimationFrame(render);

  // --- 3.8 Odbior danych z serwera --------------------------------------------
  context.onControlMessage((data) => {
    if (data.type !== 'lidar_points') return;
    const points = data.points || [];

    setPoints(points);

    if (slamActive) {
      processSlamScan(points.map((p) => correctLidarPoint(p)));
    }

    updateThreatGrid(points);
  });

  // --- 3.9 Pozostale UI: start/stop streamu, obrot/reset/zoom widoku ---------
  let pollTimer = null;

  function startPolling() {
    if (pollTimer) return;
    context.sendControl({ type: 'get_lidar_points' });
    pollTimer = setInterval(() => {
      context.sendControl({ type: 'get_lidar_points' });
    }, 500);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  if (startBtn) startBtn.addEventListener('click', startPolling);
  if (stopBtn) stopBtn.addEventListener('click', stopPolling);

  function rotateAxis(axis) {
    rotationDeg[axis] = (rotationDeg[axis] + 90) % 360;
    updateRotationLabel();
  }

  if (rotateXBtn) rotateXBtn.addEventListener('click', () => rotateAxis('x'));
  if (rotateYBtn) rotateYBtn.addEventListener('click', () => rotateAxis('y'));
  if (rotateZBtn) rotateZBtn.addEventListener('click', () => rotateAxis('z'));

  if (resetRotationBtn) {
    resetRotationBtn.addEventListener('click', () => {
      Object.assign(rotationDeg, DEFAULT_ROTATION_DEG);
      updateRotationLabel();
    });
  }

  if (resetViewBtn) {
    resetViewBtn.addEventListener('click', () => {
      Object.assign(camera, DEFAULT_CAMERA);
    });
  }

  if (zoomInBtn) zoomInBtn.addEventListener('click', () => zoomBy(0.8));
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => zoomBy(1.25));
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    perspectiveMat4,
    lookAtMat4,
    rotateXMat4,
    rotateYMat4,
    rotateZMat4,
    multiplyMat4,
    lidarPointsToRenderBuffer,
    initLidarTab,
  };
}
