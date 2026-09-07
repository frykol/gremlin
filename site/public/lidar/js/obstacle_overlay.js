// gremlin/site/public/lidar/js/obstacle_overlay.js
/**
 * Nakladka 3D pokazujaca wykryte klastry-przeszkody (z backend/lidar/
 * obstacle_clustering.py) jako wireframe bounding boxy na tle chmury
 * punktow - pula prealokowanych LineSegments (jak ring buffer punktow),
 * zeby update co ramke nie tworzyl/nie usuwal geometrii.
 */
function createObstacleOverlay(THREE, maxClusters) {
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({ color: 0x4ee6c8 });
  const boxes = [];

  const EDGE_PAIRS = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ];

  for (let i = 0; i < maxClusters; i++) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(EDGE_PAIRS.length * 2 * 3), 3));
    const lineSegments = new THREE.LineSegments(geometry, material);
    lineSegments.visible = false;
    group.add(lineSegments);
    boxes.push(lineSegments);
  }

  // Uklad lidaru: x=prawo, y=przod, z=gora; Three.js: y=gora -> ta sama
  // zamiana osi co w pointcloud.js (three.y=lidar.z, three.z=lidar.y).
  function writeBoxEdges(target, xMin, xMax, yMin, yMax, zMin, zMax) {
    const tx0 = xMin, tx1 = xMax;
    const ty0 = zMin, ty1 = zMax;
    const tz0 = yMin, tz1 = yMax;
    const corners = [
      [tx0, ty0, tz0], [tx1, ty0, tz0], [tx1, ty1, tz0], [tx0, ty1, tz0],
      [tx0, ty0, tz1], [tx1, ty0, tz1], [tx1, ty1, tz1], [tx0, ty1, tz1],
    ];
    EDGE_PAIRS.forEach(([a, b], i) => {
      const ca = corners[a];
      const cb = corners[b];
      const off = i * 6;
      target[off] = ca[0]; target[off + 1] = ca[1]; target[off + 2] = ca[2];
      target[off + 3] = cb[0]; target[off + 4] = cb[1]; target[off + 5] = cb[2];
    });
  }

  function update(clusters) {
    const count = Math.min(clusters.length, maxClusters);
    for (let i = 0; i < maxClusters; i++) {
      const box = boxes[i];
      if (i < count) {
        const c = clusters[i];
        const posAttr = box.geometry.getAttribute('position');
        writeBoxEdges(posAttr.array, c.xMin, c.xMax, c.yMin, c.yMax, c.zMin, c.zMax);
        posAttr.needsUpdate = true;
        box.visible = true;
      } else {
        box.visible = false;
      }
    }
  }

  return { object: group, update };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createObstacleOverlay };
} else {
  window.createObstacleOverlay = createObstacleOverlay;
}
