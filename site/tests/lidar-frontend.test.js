const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const publicDir = path.join(__dirname, '..', 'public');

test('LiDAR tab exposes the Three.js viewer contract', () => {
    const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
    const tab = fs.readFileSync(path.join(publicDir, 'tabs', 'lidar.js'), 'utf8');

    assert.match(html, /id="viewer-canvas"/);
    assert.match(html, /id="connection-banner"/);
    assert.match(tab, /\/ws\/lidar/);
    assert.match(tab, /createViewer/);
    assert.match(tab, /createImuPanel/);
    assert.match(tab, /createMetricsPanel/);
});

test('LiDAR module assets are available locally', () => {
    for (const asset of [
        'js/vendor/three.min.js',
        'js/color.js',
        'js/viewer.js',
        'js/pointcloud.js',
        'js/imu_panel.js',
        'js/metrics_panel.js',
        'js/ws_client.js',
    ]) {
        assert.equal(fs.existsSync(path.join(publicDir, 'lidar', asset)), true, asset);
    }
});