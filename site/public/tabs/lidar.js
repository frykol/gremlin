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

// Punkty z lidaru przychodza jako [x, y, z] gdzie y = do przodu, z = w gore.
// Na potrzeby renderowania (Y w gore, Z w strone kamery) zamieniamy osie.
function lidarPointsToRenderBuffer(points) {
  const flat = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    flat[i * 3] = p[0];
    flat[i * 3 + 1] = p[2];
    flat[i * 3 + 2] = p[1];
  }
  return flat;
}

// Lidar jest fizycznie zamontowany na boku (obrocony wokol osi "do przodu"),
// wiec domyslnie doliczamy korekte 90 stopni rolu (obrot wokol osi Z w
// przestrzeni renderowania), zeby "gora" czujnika odpowiadala prawdziwej
// pionowej osi robota.
const DEFAULT_ROTATION_DEG = { x: 0, y: 0, z: 90 };

function initLidarTab(context) {
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
    uniform mat4 uProjection;
    uniform mat4 uView;
    uniform mat4 uModel;
    varying float vDistance;
    void main() {
      vec4 worldPos = uModel * vec4(aPosition, 1.0);
      gl_Position = uProjection * uView * worldPos;
      gl_PointSize = 3.0;
      vDistance = length(worldPos.xyz);
    }
  `;
  const fsSource = `
    precision mediump float;
    varying float vDistance;
    uniform float uMaxDistance;
    void main() {
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
  const uProjection = gl.getUniformLocation(program, 'uProjection');
  const uView = gl.getUniformLocation(program, 'uView');
  const uModel = gl.getUniformLocation(program, 'uModel');
  const uMaxDistance = gl.getUniformLocation(program, 'uMaxDistance');

  const vertexBuffer = gl.createBuffer();
  let pointCount = 0;
  let maxDistance = 1.0;

  // Obrot calej chmury punktow, niezalezny od kamery. Kazda os liczona
  // osobno i pokazywana w etykiecie, zeby latwo bylo trafic w 90/180/270.
  const rotationDeg = { ...DEFAULT_ROTATION_DEG };

  function updateRotationLabel() {
    if (rotationLabel) {
      rotationLabel.textContent = `obrót X:${rotationDeg.x}° Y:${rotationDeg.y}° Z:${rotationDeg.z}°`;
    }
  }
  updateRotationLabel();

  function setPoints(points) {
    const flat = lidarPointsToRenderBuffer(points);
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, flat, gl.DYNAMIC_DRAW);
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

  // --- kamera orbitalna (przeciaganie = obrot, scroll/przyciski = zoom) ---
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

  let rafId = null;

  function render() {
    resizeIfNeeded();
    gl.clearColor(0.05, 0.06, 0.09, 1.0);
    gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    if (pointCount > 0) {
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
      gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.uniformMatrix4fv(uProjection, false, proj);
      gl.uniformMatrix4fv(uView, false, view);
      gl.uniformMatrix4fv(uModel, false, model);
      gl.uniform1f(uMaxDistance, maxDistance);
      gl.drawArrays(gl.POINTS, 0, pointCount);
    }

    rafId = requestAnimationFrame(render);
  }

  rafId = requestAnimationFrame(render);

  context.onControlMessage((data) => {
    if (data.type !== 'lidar_points') return;
    setPoints(data.points || []);
  });

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
