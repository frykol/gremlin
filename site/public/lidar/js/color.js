// gremlin/lidar_viewer/frontend/js/color.js
/**
 * Mapuje intensywnosc odbicia na kolor RGB (0-1 kazdy kanal), z
 * automatyczna normalizacja min/max przekazywana przez wywolujacego (okno
 * danych zmienia sie w czasie, wiec normalizacja nie jest stala).
 * Gradient: niebieski (slabe odbicie) -> zolty -> czerwony (silne odbicie).
 */
function intensityToColor(intensity, minIntensity, maxIntensity) {
  const range = maxIntensity - minIntensity;
  let t = range > 0 ? (intensity - minIntensity) / range : 0.5;
  t = Math.max(0, Math.min(1, t)); // clamp, nie ekstrapoluj

  const stops = [
    [0.1, 0.3, 0.9], // niebieski
    [0.95, 0.8, 0.2], // zolty
    [0.9, 0.15, 0.15], // czerwony
  ];
  const scaled = t * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const localT = scaled - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [
    a[0] + (b[0] - a[0]) * localT,
    a[1] + (b[1] - a[1]) * localT,
    a[2] + (b[2] - a[2]) * localT,
  ];
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { intensityToColor };
} else {
  window.intensityToColor = intensityToColor;
}
