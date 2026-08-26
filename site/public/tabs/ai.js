// Uproszczona mapa lokalna (occupancy grid) budowana z punktow LiDAR
// (rzut na plaszczyzne X/Y, ignorujemy wysokosc) + A* do najkrotszej sciezki.
// To NIE jest pelny SLAM (brak fuzji z odometria / zamykania petli) -
// mapa jest tylko lokalna, wokol biezacej pozycji robota w (0,0).
//
// Ten plik zawiera tylko czysta logike (siatka, A*, konwersja sciezki na
// komendy jazdy). Rendering (na scenie 3D LiDAR-u) i UI sa w tabs/lidar.js.

const AI_GRID_SIZE = 80; // komorek na bok
const AI_CELL_SIZE = 0.15; // metry na komorke
const AI_ORIGIN = Math.floor(AI_GRID_SIZE / 2);
const AI_HIT_THRESHOLD = 2; // ile trafien LiDAR-u zanim komorka = przeszkoda
const AI_PREDICTION_STEPS = 3; // ile cykli mapowania (~500ms kazdy) w przod ekstrapolujemy trend

function aiWorldToGrid(x, y) {
  return {
    gx: AI_ORIGIN + Math.round(x / AI_CELL_SIZE),
    gy: AI_ORIGIN + Math.round(y / AI_CELL_SIZE),
  };
}

function aiGridToWorld(gx, gy) {
  return {
    x: (gx - AI_ORIGIN) * AI_CELL_SIZE,
    y: (gy - AI_ORIGIN) * AI_CELL_SIZE,
  };
}

function aiInBounds(gx, gy) {
  return gx >= 0 && gy >= 0 && gx < AI_GRID_SIZE && gy < AI_GRID_SIZE;
}

// Ekstrapoluje trend zapelniania kazdej komorki (roznica hits vs prevHits =
// przyrost/zanik trafien miedzy dwoma kolejnymi skanami) o "steps" cykli w
// przod. Komorka, ktora w kilku ostatnich skanach systematycznie zbiera
// trafienia (np. zbliza sie do niej przeszkoda / robot sie do niej zbliza),
// przekroczy w ten sposob prog wczesniej niz surowe "hits" - dzieki temu
// A* moze ja ominac zanim faktycznie stanie sie przeszkoda.
function aiPredictOccupancy(hits, prevHits, steps = AI_PREDICTION_STEPS) {
  const predicted = new Float32Array(hits.length);
  for (let i = 0; i < hits.length; i++) {
    const trend = hits[i] - (prevHits[i] || 0);
    predicted[i] = Math.max(0, hits[i] + trend * steps);
  }
  return predicted;
}

// A* na siatce, ruch w 8 kierunkach. Opcjonalny predictedHits (patrz
// aiPredictOccupancy) blokuje tez komorki, ktore jeszcze nie sa przeszkoda,
// ale trend wskazuje, ze zaraz nia beda.
function aiFindPath(hits, start, goal, predictedHits = null) {
  if (!aiInBounds(start.gx, start.gy) || !aiInBounds(goal.gx, goal.gy)) return null;

  const key = (gx, gy) => gy * AI_GRID_SIZE + gx;
  const isBlocked = (gx, gy) => {
    const idx = key(gx, gy);
    if ((hits[idx] || 0) >= AI_HIT_THRESHOLD) return true;
    if (predictedHits && (predictedHits[idx] || 0) >= AI_HIT_THRESHOLD) return true;
    return false;
  };
  if (isBlocked(goal.gx, goal.gy)) return null;

  const neighbors = [
    [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
    [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2],
  ];

  const h = (gx, gy) => Math.hypot(gx - goal.gx, gy - goal.gy);
  const open = new Map();
  const gScore = new Map();
  const cameFrom = new Map();
  const startKey = key(start.gx, start.gy);
  gScore.set(startKey, 0);
  open.set(startKey, h(start.gx, start.gy));

  while (open.size > 0) {
    let currentKey = null;
    let bestF = Infinity;
    for (const [k, f] of open) {
      if (f < bestF) { bestF = f; currentKey = k; }
    }
    if (currentKey === null) break;

    const cgx = currentKey % AI_GRID_SIZE;
    const cgy = Math.floor(currentKey / AI_GRID_SIZE);
    if (cgx === goal.gx && cgy === goal.gy) {
      const path = [{ gx: cgx, gy: cgy }];
      let k = currentKey;
      while (cameFrom.has(k)) {
        k = cameFrom.get(k);
        path.push({ gx: k % AI_GRID_SIZE, gy: Math.floor(k / AI_GRID_SIZE) });
      }
      path.reverse();
      return path;
    }

    open.delete(currentKey);

    for (const [dx, dy, cost] of neighbors) {
      const ngx = cgx + dx;
      const ngy = cgy + dy;
      if (!aiInBounds(ngx, ngy) || isBlocked(ngx, ngy)) continue;

      const nKey = key(ngx, ngy);
      const tentativeG = (gScore.get(currentKey) ?? Infinity) + cost;
      if (tentativeG < (gScore.get(nKey) ?? Infinity)) {
        cameFrom.set(nKey, currentKey);
        gScore.set(nKey, tentativeG);
        open.set(nKey, tentativeG + h(ngx, ngy));
      }
    }
  }

  return null;
}

// Zamienia sciezke (komorki siatki) na sekwencje komend jazdy zgodnych
// z kierunkami zdefiniowanymi w control.js (DIRECTIONS / computeChannelValues).
// Zalozenie upraszczajace: "przod" robota = rosnace gy. Brak sprzezenia
// zwrotnego z rzeczywistym kursem (open-loop), wiec to demonstracja, nie
// nawigacja produkcyjna.
function aiPathToSteps(path) {
  const steps = [];
  for (let i = 1; i < path.length; i++) {
    const dx = path[i].gx - path[i - 1].gx;
    const dy = path[i].gy - path[i - 1].gy;

    let direction;
    if (dx === 0 && dy > 0) direction = 'Przód';
    else if (dx === 0 && dy < 0) direction = 'Tył';
    else if (dx > 0 && dy === 0) direction = 'Prawo';
    else if (dx < 0 && dy === 0) direction = 'Lewo';
    else if (dx > 0 && dy > 0) direction = 'Full prawo';
    else if (dx < 0 && dy > 0) direction = 'Full lewo';
    else if (dx > 0 && dy < 0) direction = 'Prawo';
    else direction = 'Lewo';

    const last = steps[steps.length - 1];
    if (last && last.direction === direction) {
      last.cells += 1;
    } else {
      steps.push({ direction, cells: 1 });
    }
  }
  return steps;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    AI_GRID_SIZE,
    AI_CELL_SIZE,
    AI_ORIGIN,
    AI_HIT_THRESHOLD,
    AI_PREDICTION_STEPS,
    aiWorldToGrid,
    aiGridToWorld,
    aiInBounds,
    aiPredictOccupancy,
    aiFindPath,
    aiPathToSteps,
  };
}
