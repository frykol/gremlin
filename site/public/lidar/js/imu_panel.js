// gremlin/lidar_viewer/frontend/js/imu_panel.js
function createImuPanel(containerEl) {
  function update({ quaternion, angularVelocity, linearAcceleration }) {
    containerEl.textContent =
      `quat [x,y,z,w] = [${Array.from(quaternion).map((v) => v.toFixed(3)).join(', ')}]\n` +
      `ang.vel = [${Array.from(angularVelocity).map((v) => v.toFixed(3)).join(', ')}]\n` +
      `lin.acc = [${Array.from(linearAcceleration).map((v) => v.toFixed(3)).join(', ')}]`;
  }
  return { update };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createImuPanel };
} else {
  window.createImuPanel = createImuPanel;
}
