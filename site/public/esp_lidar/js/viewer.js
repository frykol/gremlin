// Scena Three.js dla zakladki "ESP LiDAR" - kopia kamery orbitalnej z
// site/public/lidar/js/viewer.js, ale bez obstacle overlay (ESP tego nie
// wysyla). IMU jest obslugiwane (patrz setImuOrientation nizej) - ESP
// wysyla teraz message type 2 (quaternion+angvel+linacc, identyczny
// format co Unitree L1, patrz esp_rasp_test/PROTOCOL.txt).
function createEspObstacleLayer(THREE) {
  const group = new THREE.Group();

  function clear() {
    while (group.children.length > 0) {
      const child = group.children[group.children.length - 1];
      group.remove(child);
      if (child.geometry?.dispose) child.geometry.dispose();
      if (child.material?.dispose) child.material.dispose();
    }
  }

  function setObstacles(obstacles) {
    clear();
    for (const obstacle of obstacles || []) {
      const width = obstacle.xMax - obstacle.xMin;
      const height = obstacle.zMax - obstacle.zMin;
      const depth = obstacle.yMax - obstacle.yMin;
      const values = [width, height, depth, obstacle.centroidX, obstacle.centroidY, obstacle.centroidZ];
      if (!values.every(Number.isFinite) || width <= 0 || height <= 0 || depth <= 0) continue;

      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(width, height, depth),
        new THREE.MeshBasicMaterial({
          color: 0xff2020,
          transparent: true,
          opacity: 0.35,
          depthWrite: false,
        })
      );
      mesh.position.set(-obstacle.centroidX, obstacle.centroidZ, obstacle.centroidY);
      group.add(mesh);
    }
  }

  return { group, setObstacles, clear };
}

function createEspViewer(canvas) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);

  const sizeElement = canvas.parentElement;
  const initialW = sizeElement?.clientWidth || canvas.clientWidth || 1;
  const initialH = sizeElement?.clientHeight || canvas.clientHeight || 1;

  const camera = new THREE.PerspectiveCamera(55, initialW / initialH, 0.01, 200);
  const cameraState = { radius: 2.5, theta: 0.9, phi: 1.15 };

  function updateCameraPosition() {
    const sinPhi = Math.sin(cameraState.phi);
    camera.position.set(
      cameraState.radius * sinPhi * Math.sin(cameraState.theta),
      cameraState.radius * Math.cos(cameraState.phi),
      cameraState.radius * sinPhi * Math.cos(cameraState.theta)
    );
    camera.lookAt(0, 0, 0);
  }
  updateCameraPosition();

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(initialW, initialH, false);

  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  canvas.addEventListener('mousedown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    cameraState.theta -= dx * 0.005;
    cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi - dy * 0.005));
    updateCameraPosition();
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    cameraState.radius = Math.max(0.5, Math.min(30, cameraState.radius + e.deltaY * 0.003));
    updateCameraPosition();
  }, { passive: false });

  const grid = new THREE.GridHelper(10, 50, 0x2a3550, 0x1a2236);
  scene.add(grid);

  const cloud = createEspPointCloud(THREE);
  const obstacleLayer = createEspObstacleLayer(THREE);
  const sensorObject = new THREE.Group();
  sensorObject.add(cloud.object);
  sensorObject.add(obstacleLayer.group);
  scene.add(sensorObject);

  // Obrot calej chmury wg orientacji z IMU: caly THREE.Points dostaje
  // kwaternion zamiast przeliczania kazdego punktu osobno, zeby stare i
  // punkty w aktualnej ramce obracaly sie razem, spojnie.
  //
  // WAZNE - kolejnosc skladowych: protokol mowi "one UDP datagram per
  // Unitree IMU MAVLink packet" (esp_rasp_test/PROTOCOL.txt) - MAVLink
  // ATTITUDE_QUATERNION uzywa kolejnosci (w,x,y,z), skalar PIERWSZY, w
  // odroznieniu od (x,y,z,w) zalozonego w site/public/lidar/js/viewer.js
  // dla Unitree L1 (tam bridge SDK przepakowuje dane do wlasnej struktury,
  // wiec kolejnosc jest inna niz surowy MAVLink). Zla kolejnosc skladowych
  // daje nie czyste "do gory nogami", tylko przypadkowy, skosny obrot -
  // dokladnie to bylo obserwowane (przechylenie ~45 stopni) przy zalozeniu
  // (x,y,z,w).
  //
  // Zamiana osi: pointcloud.js mapuje pozycje ESP (x,y,z) na Three.js jako
  // (-x, z, y) - swiadomie NIE sama zamiana Y<->Z (jak w L1), bo goly swap
  // dwoch osi to odbicie lustrzane (wyznacznik -1); z dodatkowym -x cala
  // transformacja jest wlasciwym obrotem (wyznacznik +1) - patrz komentarz
  // w pointcloud.js. Konjugacja kwaternionu musi uzywac DOKLADNIE tej
  // samej transformacji na czesci wektorowej (x,y,z), zeby obrot obiektu
  // byl spojny z ukladem, w ktorym zapisane sa pozycje punktow: skoro
  // threeX=-x, threeY=z, threeZ=y, to os obrotu transformuje sie tak samo
  // (czesc skalarna w niezmienna).
  // Chmura i boxy sa jednym obiektem, dlatego reczny tilt oraz IMU zawsze
  // obracaja oba typy danych identycznie.
  function applyEspFrameQuaternion(qx, qy, qz, qw) {
    sensorObject.quaternion.set(-qx, qz, qy, qw);
  }

  // Stala doregulacja X/Y/Z (w ukladzie ESP, PRZED zamiana osi) doklejana
  // do KAZDEGO odczytu IMU - montaz IMU wzgledem lidaru moze miec swoj
  // wlasny staly offset w KAZDEJ z 3 osi, ktorego samo IMU nie widzi
  // (mierzy tylko swoja wlasna orientacje). Skladana w ukladzie ESP jako
  // qImu * qOffset (offset stosowany NAJPIERW, w lokalnym/body frame,
  // potem obrot z IMU) - zeby byla to poprawka "na sztywno przykrecona do
  // obudowy", a nie obrot w ukladzie swiata. qOffset budowany z Euler
  // X->Y->Z, tak samo jak setManualTilt.
  const _imuQuat = new THREE.Quaternion();
  const _imuOffsetEuler = new THREE.Euler(0, 0, 0, 'XYZ');
  const _imuOffsetQuat = new THREE.Quaternion();
  const _imuOffsetDeg = { x: 0, y: 0, z: 0 };
  let _imuOffsetActive = false;
  let _lastImuQuaternion = null;

  function setImuOffsetDeg(rxDeg, ryDeg, rzDeg) {
    _imuOffsetDeg.x = rxDeg;
    _imuOffsetDeg.y = ryDeg;
    _imuOffsetDeg.z = rzDeg;
    _imuOffsetActive = rxDeg !== 0 || ryDeg !== 0 || rzDeg !== 0;
    _imuOffsetEuler.set((rxDeg * Math.PI) / 180, (ryDeg * Math.PI) / 180, (rzDeg * Math.PI) / 180, 'XYZ');
    _imuOffsetQuat.setFromEuler(_imuOffsetEuler);
    if (_lastImuQuaternion) setImuOrientation(_lastImuQuaternion);
  }
  // Wstecznie kompatybilny helper - tylko X, reszta zostaje bez zmian.
  function setImuOffsetXDeg(deg) {
    setImuOffsetDeg(deg, _imuOffsetDeg.y, _imuOffsetDeg.z);
  }
  setImuOffsetDeg(0, 0, 0);

  function setImuOrientation(quaternion) {
    if (!quaternion || quaternion.length < 4) return;
    _lastImuQuaternion = Array.from(quaternion);
    const qw = quaternion[0], qx = quaternion[1], qy = quaternion[2], qz = quaternion[3];
    _imuQuat.set(qx, qy, qz, qw);
    if (_imuOffsetActive) {
      _imuQuat.multiply(_imuOffsetQuat);
    }
    applyEspFrameQuaternion(_imuQuat.x, _imuQuat.y, _imuQuat.z, _imuQuat.w);
  }

  // Reczna korekta montazu (suwaki w zakladce) - stosowana TERAZ na
  // poziomie calego obiektu (tak samo jak IMU), a NIE per-punkt przy
  // zapisie do bufora (patrz duzy komentarz na gorze pointcloud.js po co).
  // Katy definiowane w ukladzie ESP (przed zamiana osi), kolejnosc X->Y->Z,
  // wiec konwersja na kwaternion i konjugacja przez ten sam remap co IMU.
  const _manualEuler = new THREE.Euler(0, 0, 0, 'XYZ');
  const _manualQuat = new THREE.Quaternion();
  function setManualTilt(rxDeg, ryDeg, rzDeg) {
    _manualEuler.set(
      (rxDeg * Math.PI) / 180,
      (ryDeg * Math.PI) / 180,
      (rzDeg * Math.PI) / 180,
      'XYZ'
    );
    _manualQuat.setFromEuler(_manualEuler);
    applyEspFrameQuaternion(_manualQuat.x, _manualQuat.y, _manualQuat.z, _manualQuat.w);
  }

  function onResize() {
    const w = sizeElement?.clientWidth || canvas.clientWidth;
    const h = sizeElement?.clientHeight || canvas.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  window.addEventListener('resize', onResize);

  if (typeof ResizeObserver !== 'undefined') {
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(sizeElement || canvas);
  }

  function render() {
    requestAnimationFrame(render);
    renderer.render(scene, camera);
  }

  return {
    scene,
    camera,
    renderer,
    render,
    setPoints: (flatXyzIntensity, pointCount) => cloud.update(flatXyzIntensity, pointCount, window.intensityToColor),
    setImuOrientation,
    setManualTilt,
    setImuOffsetXDeg,
    setImuOffsetDeg,
    setObstacles: obstacleLayer.setObstacles,
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createEspObstacleLayer, createEspViewer };
} else {
  window.createEspObstacleLayer = createEspObstacleLayer;
  window.createEspViewer = createEspViewer;
}
