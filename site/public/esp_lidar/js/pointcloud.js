// Chmura punktow dla zakladki "ESP LiDAR" - pokazuje tylko ostatnia pelna
// ramke otrzymana z backendu.
//
// WAZNE: tutaj NIE piecze sie zadnej korekty orientacji (suwaki/IMU) w
// pozycje punktow przy zapisie do ramki. Wczesniejsza wersja robila to
// per-punkt, w momencie przyjecia go do bufora - co oznaczalo, ze zmiana
// suwaki dotyczyla TYLKO nowych punktow, a stare zostawaly zamrozone w
// poprzedniej orientacji. Efekt: obraz nigdy
// sie nie "domyka" w spojna, pozioma calosc, niezaleznie od ustawien
// suwakow. Korekta orientacji (reczna z suwakow ALBO z IMU) jest teraz
// stosowana raz, na poziomie CALEGO obiektu THREE.Points (viewer.js
// setManualTilt/setImuOrientation) - dzieki temu zmiana dziala natychmiast
// na WSZYSTKICH punktach aktualnej ramki.
const ESP_INTENSITY_COLOR_MIN = 0;
const ESP_INTENSITY_COLOR_MAX = 255;

function createEspPointCloud(THREE) {
  const positions = new Float32Array(0);
  const colors = new Float32Array(0);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setDrawRange(0, 0);

  const material = new THREE.PointsMaterial({ size: 0.03, vertexColors: true });
  const points = new THREE.Points(geometry, material);

  function clear() {
    geometry.setDrawRange(0, 0);
  }

  function update(flatXyzIntensity, pointCount, intensityToColor) {
    const count = Math.min(pointCount, Math.floor(flatXyzIntensity.length / 4));

    if (count === 0) {
      clear();
      return;
    }

    const posAttr = geometry.getAttribute('position');

    if (posAttr.array.length !== count * 3) {
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    }

    const currentPosAttr = geometry.getAttribute('position');
    const currentColorAttr = geometry.getAttribute('color');

    for (let i = 0; i < count; i++) {
      const x = flatXyzIntensity[i * 4 + 0];
      const y = flatXyzIntensity[i * 4 + 1];
      const z = flatXyzIntensity[i * 4 + 2];
      const intensity = flatXyzIntensity[i * 4 + 3];

      const [r, g, b] = intensityToColor(intensity, ESP_INTENSITY_COLOR_MIN, ESP_INTENSITY_COLOR_MAX);

      const slot = i * 3;
      // uklad ESP: Z=gora; Three.js: Y=gora -> zamiana osi Y<->Z. Sama
      // zamiana dwoch osi to odbicie lustrzane (wyznacznik -1) - dodatkowe
      // -x sprawia, ze cala transformacja jest wlasciwym obrotem
      // (wyznacznik +1). Orientacja (montaz/IMU) jest doklejana PO tym
      // remapie, na poziomie calego obiektu - patrz viewer.js.
      currentPosAttr.array[slot + 0] = -x;
      currentPosAttr.array[slot + 1] = z;
      currentPosAttr.array[slot + 2] = y;

      currentColorAttr.array[slot + 0] = r;
      currentColorAttr.array[slot + 1] = g;
      currentColorAttr.array[slot + 2] = b;

    }

    currentPosAttr.needsUpdate = true;
    currentColorAttr.needsUpdate = true;
    geometry.setDrawRange(0, count);
  }

  return { object: points, update, clear };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createEspPointCloud };
} else {
  window.createEspPointCloud = createEspPointCloud;
}
