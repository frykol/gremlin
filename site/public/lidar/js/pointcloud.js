// gremlin/lidar_viewer/frontend/js/pointcloud.js
/**
 * Owija THREE.Points z preallokowanymi buforami, zeby aktualizacja co
 * ramke Scan nie przebudowywala calej geometrii (kosztowne przy live
 * streamie) - tylko .set() na istniejacej Float32Array + needsUpdate.
 */
// Korekta orientacji montazu LiDAR-u, dobrana recznie suwakami na zywo
// (patrzac na prawdziwy pokoj). Wbudowana na stale - suwaki w zakladce
// Lidar startuja od 0 i dokladaja SIE do tej bazy (0 na suwaku = ta baza,
// bez dodatkowej korekty).
const BASE_TILT_X_DEG = -122;
const BASE_TILT_Y_DEG = 19;
const BASE_TILT_Z_DEG = -11;

// Stala (nie liczona na nowo co ramke) skala intensywnosci do kolorowania.
// Zmierzone empirycznie z realnych danych L1 (650k punktow, patrz
// brainstorming w rozmowie): skala natywna to 0-255, ale 5/95 percentyl to
// 86/234 - te wartosci daja lepszy kontrast (wiekszosc realnych danych
// wypelnia caly gradient) niz pelne 0-255 (gdzie glowna masa danych
// stloczylaby sie w waskim srodkowym pasie). Poprzednio przeliczane PER
// RAMKA (min/max biezacej paczki) - to dawalo niespojne kolory w czasie,
// bo ten sam fizyczny odczyt wygladal inaczej w zaleznosci od tego, co
// jeszcze bylo w danej paczce.
const INTENSITY_COLOR_MIN = 86;
const INTENSITY_COLOR_MAX = 234;

function createPointCloud(THREE, maxPoints) {
  const positions = new Float32Array(maxPoints * 3);
  const colors = new Float32Array(maxPoints * 3);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setDrawRange(0, 0);

  const material = new THREE.PointsMaterial({ size: 0.03, vertexColors: true });
  const points = new THREE.Points(geometry, material);

  // Ring buffer: kazda nowa ramka Scan DOPISUJE punkty od miejsca, gdzie
  // skonczyla poprzednia (zamiast nadpisywac caly bufor od indeksu 0), a
  // po zapelnieniu maxPoints zawija sie i zaczyna nadpisywac najstarsze
  // punkty. Dzieki temu chmura nie znika/nie miga miedzy kolejnymi
  // (niepelnymi) ramkami - narasta i utrzymuje sie, tak jak akumulacja po
  // stronie backendu, tylko jeszcze dluzej.
  let writeCursor = 0;
  let filledCount = 0;

  // Odczyt doregulacji z suwakow, odporny na brak `window` - modul jest
  // eksportowany takze jako CommonJS (patrz koniec pliku) i uruchamiany w
  // testach pod Node, gdzie golego `window` nie ma.
  function tiltOverride(name) {
    if (typeof window === 'undefined') return 0;
    return window[name] || 0;
  }

  function clear() {
    writeCursor = 0;
    filledCount = 0;
    geometry.setDrawRange(0, 0);
  }

  function update(flatXyzIntensity, pointCount, intensityToColor) {
    const count = Math.min(pointCount, maxPoints);

    // Pusta ramka Scan to CELOWY sygnal z backendu "zrodlo danych padlo /
    // okno jest puste" (backend/lidar/app.py wysyla ja przy przejsciu
    // "byly punkty -> nie ma punktow"). Bez wyczyszczenia pierscienia
    // chmura zostawalaby na ekranie w nieskonczonosc i wygladala na zywa -
    // dokladnie stan "wyglada, ze dziala, a nie dziala", ktorego spec
    // zabrania.
    if (count === 0) {
      clear();
      return;
    }

    const posAttr = geometry.getAttribute('position');
    const colorAttr = geometry.getAttribute('color');

    // Baza (BASE_TILT_*) + dodatkowa doregulacja z suwakow (domyslnie 0 -
    // czyli sama baza, bez zmian). Rotacje stosowane w kolejnosci
    // X -> Y -> Z, PRZED zamiana osi na uklad Three.js (patrz nizej).
    const rxDeg = BASE_TILT_X_DEG + tiltOverride('LIDAR_TILT_X_DEG');
    const ryDeg = BASE_TILT_Y_DEG + tiltOverride('LIDAR_TILT_Y_DEG');
    const rzDeg = BASE_TILT_Z_DEG + tiltOverride('LIDAR_TILT_Z_DEG');
    const rx = (rxDeg * Math.PI) / 180;
    const ry = (ryDeg * Math.PI) / 180;
    const rz = (rzDeg * Math.PI) / 180;
    const cx = Math.cos(rx), sx = Math.sin(rx);
    const cy = Math.cos(ry), sy = Math.sin(ry);
    const cz = Math.cos(rz), sz = Math.sin(rz);

    for (let i = 0; i < count; i++) {
      let x = flatXyzIntensity[i * 4 + 0];
      let y = flatXyzIntensity[i * 4 + 1];
      let z = flatXyzIntensity[i * 4 + 2];
      const intensity = flatXyzIntensity[i * 4 + 3];

      // Rotacja X (pitch, wokol osi x)
      let ry1 = cx * y - sx * z;
      let rz1 = sx * y + cx * z;
      y = ry1; z = rz1;

      // Rotacja Y (yaw, wokol osi y)
      let rx2 = cy * x + sy * z;
      let rz2 = -sy * x + cy * z;
      x = rx2; z = rz2;

      // Rotacja Z (roll, wokol osi z)
      let rx3 = cz * x - sz * y;
      let ry3 = sz * x + cz * y;
      x = rx3; y = ry3;

      const [r, g, b] = intensityToColor(intensity, INTENSITY_COLOR_MIN, INTENSITY_COLOR_MAX);

      // Zapis do pierscienia pod writeCursor (nie pod i) - to wlasnie
      // realizuje "dopisuj, a po zapelnieniu nadpisuj najstarsze".
      const slot = writeCursor * 3;
      // uklad lidaru: Z=gora; Three.js: Y=gora -> zamiana osi
      posAttr.array[slot + 0] = x;
      posAttr.array[slot + 1] = z;
      posAttr.array[slot + 2] = y;

      colorAttr.array[slot + 0] = r;
      colorAttr.array[slot + 1] = g;
      colorAttr.array[slot + 2] = b;

      writeCursor = (writeCursor + 1) % maxPoints;
      if (filledCount < maxPoints) filledCount++;
    }

    posAttr.needsUpdate = true;
    colorAttr.needsUpdate = true;
    geometry.setDrawRange(0, filledCount);
  }

  return { object: points, update, clear };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createPointCloud };
} else {
  window.createPointCloud = createPointCloud;
}
