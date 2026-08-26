// Minimalne 2D SLAM: dopasowanie kolejnych skanow LiDAR do zbudowanej dotad
// mapy (scan-to-map ICP), zeby estymowac ruch robota (x, z, yaw) BEZ polegania
// na enkoderach kol. To realna wersja "prawdziwego SLAM-u" (jak np. Kitware
// LiDAR SLAM) uproszczona do 2D (plaszczyzna x/z, tj. robot jezdzi po
// podlodze i obraca sie wokol osi pionowej) - w pelni 3D LOAM z ekstrakcja
// cech krawedzi/plaszczyzn to zupelnie inna skala projektu.
//
// Ten plik zawiera tylko czysta logike (bez DOM/WebGL), zeby dalo sie ja
// przetestowac w node --test niezaleznie od przegladarki.

// Prosta siatka przestrzenna do wyszukiwania najblizszego sasiada (zamiast
// pelnego KD-tree - wystarcza przy gestosciach punktow po odszumieniu).
class SpatialGrid2D {
  constructor(points, cellSize) {
    this.cellSize = cellSize;
    this.cells = new Map();
    for (const p of points) this.insert(p);
  }

  keyFor(x, z) {
    return `${Math.floor(x / this.cellSize)},${Math.floor(z / this.cellSize)}`;
  }

  insert(p) {
    const key = this.keyFor(p.x, p.z);
    let arr = this.cells.get(key);
    if (!arr) {
      arr = [];
      this.cells.set(key, arr);
    }
    arr.push(p);
  }

  nearest(x, z, maxDist) {
    const gx = Math.floor(x / this.cellSize);
    const gz = Math.floor(z / this.cellSize);
    let best = null;
    let bestDistSq = maxDist * maxDist;

    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        const arr = this.cells.get(`${gx + dx},${gz + dz}`);
        if (!arr) continue;
        for (const q of arr) {
          const ddx = q.x - x;
          const ddz = q.z - z;
          const distSq = ddx * ddx + ddz * ddz;
          if (distSq < bestDistSq) {
            bestDistSq = distSq;
            best = q;
          }
        }
      }
    }

    return best;
  }
}

// Usrednia punkty w tej samej komorce siatki (redukcja gestosci przed ICP -
// pojedynczy skan ma dziesiatki tysiecy punktow, ICP potrzebuje raczej setek).
function voxelDownsample2D(points, cellSize) {
  const cells = new Map();
  for (const p of points) {
    const key = `${Math.floor(p.x / cellSize)},${Math.floor(p.z / cellSize)}`;
    let cell = cells.get(key);
    if (!cell) {
      cell = { x: 0, z: 0, count: 0 };
      cells.set(key, cell);
    }
    cell.x += p.x;
    cell.z += p.z;
    cell.count += 1;
  }

  const out = [];
  for (const cell of cells.values()) {
    out.push({ x: cell.x / cell.count, z: cell.z / cell.count });
  }
  return out;
}

// Stosuje transformacje sztywna 2D (rotacja o theta + przesuniecie) do punktu.
function applyPose2D(pose, p) {
  const c = Math.cos(pose.theta);
  const s = Math.sin(pose.theta);
  return {
    x: c * p.x - s * p.z + pose.tx,
    z: s * p.x + c * p.z + pose.tz,
  };
}

// Sklada dwie transformacje: wynik(p) = delta(old(p)).
function composePose2D(delta, old) {
  const c = Math.cos(delta.theta);
  const s = Math.sin(delta.theta);
  return {
    theta: old.theta + delta.theta,
    tx: c * old.tx - s * old.tz + delta.tx,
    tz: s * old.tx + c * old.tz + delta.tz,
  };
}

// Domkniete rozwiazanie 2D Procrustes (optymalna rotacja+translacja miedzy
// para dopasowanych punktow) - rownowazne metodzie z liczbami zespolonymi:
// theta = atan2(Im(sum conj(a)*b)), gdzie a,b to punkty wysrodkowane wzgledem
// wlasnych centroidow.
function alignPointPairs(sourcePts, targetPts) {
  const n = sourcePts.length;
  let cpx = 0, cpz = 0, cqx = 0, cqz = 0;
  for (let i = 0; i < n; i++) {
    cpx += sourcePts[i].x; cpz += sourcePts[i].z;
    cqx += targetPts[i].x; cqz += targetPts[i].z;
  }
  cpx /= n; cpz /= n; cqx /= n; cqz /= n;

  let C = 0, S = 0;
  for (let i = 0; i < n; i++) {
    const ax = sourcePts[i].x - cpx, az = sourcePts[i].z - cpz;
    const bx = targetPts[i].x - cqx, bz = targetPts[i].z - cqz;
    C += ax * bx + az * bz;
    S += ax * bz - az * bx;
  }

  const theta = Math.atan2(S, C);
  const c = Math.cos(theta), s = Math.sin(theta);
  const tx = cqx - (c * cpx - s * cpz);
  const tz = cqz - (s * cpx + c * cpz);

  return { theta, tx, tz };
}

// Iterative Closest Point (2D, point-to-point). `sourcePoints` to skan JUZ
// przeniesiony do przestrzeni swiata wstepnym oszacowaniem pozy (patrz
// lidar.js) - ICP znajduje MALA korekte, ktora lepiej dopasowuje go do
// dotychczasowej mapy `targetPoints`.
function icp2d(sourcePoints, targetPoints, options = {}) {
  const maxIterations = options.maxIterations ?? 20;
  const maxCorrespondenceDist = options.maxCorrespondenceDist ?? 0.5;
  const cellSize = options.cellSize ?? Math.max(0.1, maxCorrespondenceDist / 2);
  const convergenceEps = options.convergenceEps ?? 1e-5;
  const minCorrespondences = options.minCorrespondences ?? 5;

  if (sourcePoints.length < minCorrespondences || targetPoints.length < minCorrespondences) {
    return { theta: 0, tx: 0, tz: 0, meanError: Infinity, iterations: 0, converged: false };
  }

  const targetGrid = new SpatialGrid2D(targetPoints, cellSize);
  const transformed = sourcePoints.map((p) => ({ x: p.x, z: p.z }));

  let pose = { theta: 0, tx: 0, tz: 0 };
  let prevError = Infinity;
  let iterationsRun = 0;
  let converged = false;

  for (let iter = 0; iter < maxIterations; iter++) {
    iterationsRun++;

    const correspSource = [];
    const correspTarget = [];
    let sumSqError = 0;

    for (const p of transformed) {
      const match = targetGrid.nearest(p.x, p.z, maxCorrespondenceDist);
      if (!match) continue;
      correspSource.push(p);
      correspTarget.push(match);
      const dx = p.x - match.x, dz = p.z - match.z;
      sumSqError += dx * dx + dz * dz;
    }

    if (correspSource.length < minCorrespondences) break;

    const delta = alignPointPairs(correspSource, correspTarget);
    const c = Math.cos(delta.theta), s = Math.sin(delta.theta);

    for (const p of transformed) {
      const nx = c * p.x - s * p.z + delta.tx;
      const nz = s * p.x + c * p.z + delta.tz;
      p.x = nx; p.z = nz;
    }

    pose = composePose2D(delta, pose);

    const meanError = Math.sqrt(sumSqError / correspSource.length);
    if (Math.abs(prevError - meanError) < convergenceEps) {
      prevError = meanError;
      converged = true;
      break;
    }
    prevError = meanError;
  }

  return { ...pose, meanError: prevError, iterations: iterationsRun, converged };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    SpatialGrid2D,
    voxelDownsample2D,
    applyPose2D,
    composePose2D,
    alignPointPairs,
    icp2d,
  };
}
