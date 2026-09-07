// gremlin/lidar_viewer/frontend/js/viewer.js
/**
 * Scena Three.js z wlasna (bez OrbitControls) sferyczna kamera orbitalna:
 * przeciaganie mysza = obrot, kolko = zoom. To swiadoma decyzja - CDN-owy
 * OrbitControls.js byl przyczyna awarii w prototypie (404, brak
 * czytelnego bledu w UI).
 */
function createViewer(canvas, maxPoints) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);

  // Karta LiDAR jest inicjalizowana natychmiast przy starcie strony, ale
  // jej zakladka moze byc wtedy ukryta (display: none) - canvas ma wowczas
  // clientWidth/clientHeight 0. Aspect 0/0 = NaN psuloby projekcje kamery,
  // a renderer.setSize(0, 0) na starcie na niektorych GPU/sterownikach
  // trwale psuje bufor WebGL nawet po pozniejszym poprawnym resize -
  // dlatego oba uzywaja bezpiecznego fallbacku 1x1 zamiast realnego (zerowego) rozmiaru.
  const sizeElement = canvas.parentElement;
  const initialW = sizeElement?.clientWidth || canvas.clientWidth || 1;
  const initialH = sizeElement?.clientHeight || canvas.clientHeight || 1;

  const camera = new THREE.PerspectiveCamera(55, initialW / initialH, 0.01, 200);
  // Blizszy domyslny zoom (bylo 4.5m) - przy szerokim zasiegu sceny (do 8m)
  // male obiekty (np. 20cm) byly nieproporcjonalnie male na ekranie.
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

  // Oczko siatki = 0.2m (10m / 50 podzialow) - dziala jak wizualna
  // "linijka", zeby na oko oszacowac rozmiar malych obiektow (np. 20cm).
  const grid = new THREE.GridHelper(10, 50, 0x2a3550, 0x1a2236);
  scene.add(grid);

  const cloud = createPointCloud(THREE, maxPoints);
  scene.add(cloud.object);

  // Obrot calej chmury (razem z juz zapisanymi punktami) wg orientacji
  // robota z IMU. Punkty zapisywane sa w pointcloud.js w ukladzie
  // "montaz + stala korekta" (BASE_TILT_*), bez wiedzy o biezacym obrocie
  // robota - to celowe: gdyby kazdy punkt byl przeliczany na sztywno przy
  // zapisie, stare punkty zostalyby "zamrozone" w orientacji sprzed obrotu
  // i chmura rozjezdzalaby sie przy kazdym skrecie. Zamiast tego caly
  // obiekt THREE.Points dostaje quaternion z IMU - to jeden, tani obrot
  // sztywny calej geometrii, wiec stare i nowe punkty obracaja sie razem,
  // spojnie, wokol robota.
  // Zamiana osi Y<->Z odwzorowuje DOKLADNIE ta sama zamiane, ktora
  // pointcloud.js stosuje do pozycji punktow (posAttr: x, z, y - patrz
  // komentarz "uklad lidaru: Z=gora; Three.js: Y=gora"). Dla obrotu
  // (kwaternionu) to wlasnie konjugacja B*R*B^-1 zmiany bazy B (permutacja
  // Y<->Z): wektor osi obrotu przechodzi przez to samo B co kazdy inny
  // wektor (axis' = B*axis -> zamiana y i z), a kat obrotu (skladowa w)
  // jest niezmiennikiem kazdej ortogonalnej zmiany bazy - NIE ma potrzeby
  // dokladania jakiejkolwiek zmiany znaku (det(B*R*B^-1) = det(R) zawsze,
  // niezaleznie od det(B); zle zalozenie, ze reflekcja B psuje obrot, bylo
  // bledem w poprzedniej wersji tego kodu). To ten sam mechanizm, ktorym
  // BASE_TILT_X/Y/Z_DEG w pointcloud.js koryguje montaz w 3 osiach - tam
  // przez jawna macierz obrotu X->Y->Z, tu przez kwaternion z IMU,
  // konsekwentnie w tym samym ukladzie wspolrzednych co punkty.
  function imuOverride(name, fallback) {
    if (typeof window === 'undefined' || window[name] === undefined) return fallback;
    return window[name];
  }

  function setImuOrientation(quaternion) {
    if (!quaternion || quaternion.length < 4) return;
    // 0 = wylacz na czas testu - i wroc do tozsamosci (brak obrotu), a nie
    // tylko "przestan aktualizowac" (bez tego chmura zostawala zamrozona w
    // OSTATNIM zastosowanym obrocie IMU, co wygladalo jak dowod na cos
    // innego, a bylo tylko artefaktem tego przelacznika).
    if (imuOverride('LIDAR_IMU_ROTATION_ENABLED', 1) === 0) {
      cloud.object.quaternion.identity();
      return;
    }
    cloud.object.quaternion.set(quaternion[0], quaternion[2], quaternion[1], quaternion[3]);
  }

  const obstacles = createObstacleOverlay(THREE, 200);
  scene.add(obstacles.object);

  function onResize() {
    const w = sizeElement?.clientWidth || canvas.clientWidth;
    const h = sizeElement?.clientHeight || canvas.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  window.addEventListener('resize', onResize);

  // Karta LiDAR jest inicjalizowana natychmiast przy starcie strony, ale
  // jej zakladka moze byc wtedy ukryta (display: none) - canvas ma wowczas
  // clientWidth/clientHeight 0, co psuje aspect ratio kamery/renderer na
  // stale (zwykly event 'resize' okna sie wtedy nie odpala). ResizeObserver
  // wykrywa moment, w ktorym zakladka staje sie widoczna i realny rozmiar
  // jest znany.
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
    setPoints: (flatXyzIntensity, pointCount) => cloud.update(flatXyzIntensity, pointCount, intensityToColor),
    setObstacles: (clusters) => obstacles.update(clusters),
    setImuOrientation,
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createViewer };
} else {
  window.createViewer = createViewer;
}
