const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { createEspObstacleLayer } = require(
    path.join(__dirname, '..', 'public', 'esp_lidar', 'js', 'viewer.js')
);
const viewerSource = fs.readFileSync(
    path.join(__dirname, '..', 'public', 'esp_lidar', 'js', 'viewer.js'),
    'utf8'
);

function makeFakeThree() {
    class Group {
        constructor() { this.children = []; }
        add(child) { this.children.push(child); }
        remove(child) { this.children = this.children.filter((item) => item !== child); }
    }
    return {
        Group,
        BoxGeometry: class {
            constructor(width, height, depth) { this.width = width; this.height = height; this.depth = depth; }
            dispose() {}
        },
        MeshBasicMaterial: class { constructor(options) { Object.assign(this, options); } },
        Mesh: class {
            constructor(geometry, material) {
                this.geometry = geometry;
                this.material = material;
                this.position = { set: (x, y, z) => Object.assign(this.position, { x, y, z }) };
            }
        },
    };
}

test('ESP viewer exposes the IMU offset API used by the tab', () => {
    assert.match(viewerSource, /setImuOffsetXDeg,\s*setImuOffsetDeg/);
});

test('ESP obstacle layer shares the cloud angle correction object', () => {
    assert.match(viewerSource, /sensorObject\.add\(cloud\.object\)/);
    assert.match(viewerSource, /sensorObject\.add\(obstacleLayer\.group\)/);
    assert.match(viewerSource, /sensorObject\.quaternion\.set\(-qx, qz, qy, qw\)/);
});

test('IMU offset reapplies to the latest orientation immediately', () => {
    assert.match(viewerSource, /_lastImuQuaternion/);
    assert.match(viewerSource, /setImuOffsetDeg[\s\S]*_lastImuQuaternion/);
});

test('ESP obstacle layer creates a red transformed box', () => {
    const layer = createEspObstacleLayer(makeFakeThree());

    layer.setObstacles([{
        xMin: -1, xMax: 3,
        yMin: -0.5, yMax: 4.5,
        zMin: 0, zMax: 6,
        centroidX: 1, centroidY: 2, centroidZ: 3,
        pointCount: 12,
    }]);

    assert.equal(layer.group.children.length, 1);
    assert.equal(layer.group.children[0].material.color, 0xff2020);
    assert.equal(layer.group.children[0].position.x, -1);
    assert.equal(layer.group.children[0].position.y, 3);
    assert.equal(layer.group.children[0].position.z, 2);
    assert.equal(layer.group.children[0].geometry.width, 4);
    assert.equal(layer.group.children[0].geometry.height, 6);
    assert.equal(layer.group.children[0].geometry.depth, 5);
});

test('ESP obstacle layer clears on an empty frame', () => {
    const layer = createEspObstacleLayer(makeFakeThree());
    layer.setObstacles([{ xMin: 0, xMax: 1, yMin: 0, yMax: 1, zMin: 0, zMax: 1, centroidX: 0.5, centroidY: 0.5, centroidZ: 0.5 }]);

    layer.setObstacles([]);

    assert.equal(layer.group.children.length, 0);
});