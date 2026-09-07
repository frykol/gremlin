// gremlin/site/public/lidar/js/obstacle_radar.js
/**
 * Prosty widok 2D "z gory" - robot na srodku, wykryte klastry-przeszkody
 * jako prostokaty w skali. Zwykly canvas 2D (nie Three.js) - to jest
 * plaski, schematyczny podglad, nie scena 3D.
 */
function createObstacleRadar(canvas, { rangeM = 8 } = {}) {
  const ctx = canvas.getContext('2d');

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(resize).observe(canvas);
  } else {
    window.addEventListener('resize', resize);
  }

  // uklad lidaru: x=prawo, y=przod -> ekran: x w prawo, y w gore ekranu
  // (przod robota) = -y ekranu (canvas Y rosnie w dol).
  function worldToScreen(x, y, w, h) {
    const scale = Math.min(w, h) / (2 * rangeM);
    return [w / 2 + x * scale, h / 2 - y * scale];
  }

  function render(clusters) {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w === 0 || h === 0) return;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0a0e17';
    ctx.fillRect(0, 0, w, h);

    // Pierscienie odleglosci co 2m, z podpisem (bez etykiet nie bylo
    // wiadomo, czy dany pierscien to 2m czy 4m).
    ctx.strokeStyle = '#1a2236';
    ctx.lineWidth = 1;
    ctx.font = '10px monospace';
    ctx.fillStyle = '#5a6a8a';
    ctx.textBaseline = 'middle';
    const scale = Math.min(w, h) / (2 * rangeM);
    for (let r = 2; r <= rangeM; r += 2) {
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, r * scale, 0, Math.PI * 2);
      ctx.stroke();
      // Etykieta na godzinie ~3 (prawa strona pierscienia), lekko odsunieta
      // od linii, zeby nie zaslaniac obwodu.
      ctx.fillText(`${r}m`, w / 2 + r * scale + 4, h / 2);
    }

    // Robot na srodku - trojkat wskazujacy przod (+Y lidaru).
    ctx.fillStyle = '#4ee6c8';
    ctx.beginPath();
    ctx.moveTo(w / 2, h / 2 - 10);
    ctx.lineTo(w / 2 - 7, h / 2 + 8);
    ctx.lineTo(w / 2 + 7, h / 2 + 8);
    ctx.closePath();
    ctx.fill();

    // Klastry jako prostokaty (bbox w plaszczyznie XY).
    ctx.strokeStyle = '#ff7b7b';
    ctx.fillStyle = 'rgba(255, 123, 123, 0.25)';
    ctx.lineWidth = 1.5;
    for (const c of clusters) {
      const [x0, y0] = worldToScreen(c.xMin, c.yMin, w, h);
      const [x1, y1] = worldToScreen(c.xMax, c.yMax, w, h);
      const left = Math.min(x0, x1);
      const top = Math.min(y0, y1);
      const rectW = Math.max(Math.abs(x1 - x0), 2);
      const rectH = Math.max(Math.abs(y1 - y0), 2);
      ctx.fillRect(left, top, rectW, rectH);
      ctx.strokeRect(left, top, rectW, rectH);
    }
  }

  return { render };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createObstacleRadar };
} else {
  window.createObstacleRadar = createObstacleRadar;
}
