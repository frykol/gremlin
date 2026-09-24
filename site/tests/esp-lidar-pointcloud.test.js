const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { createEspPointCloud } = require(
    path.join(__dirname, '..', 'public', 'esp_lidar', 'js', 'pointcloud.js')
);

function makeFakeThree() {
    class BufferAttribute {
        constructor(array, itemSize) {
            this.array = array;
            this.itemSize = itemSize;
            this.needsUpdate = false;
        }
    }
    class BufferGeometry {
        constructor() {
            this.attributes = {};
            this.drawRange = { start: 0, count: 0 };
        }
        setAttribute(name, attr) { this.attributes[name] = attr; }
        getAttribute(name) { return this.attributes[name]; }
        setDrawRange(start, count) { this.drawRange = { start, count }; }
    }
    return {
        BufferGeometry,
        BufferAttribute,
        PointsMaterial: class { constructor(opts) { Object.assign(this, opts); } },
        Points: class { constructor(geometry, material) { this.geometry = geometry; this.material = material; } },
    };
}

const identityColor = () => [1, 1, 1];

function framePoints(n, value) {
    const arr = new Float32Array(n * 4);
    for (let i = 0; i < n; i++) {
        arr[i * 4 + 0] = value;
        arr[i * 4 + 1] = value;
        arr[i * 4 + 2] = value;
        arr[i * 4 + 3] = 150;
    }
    return arr;
}

test('ESP cloud displays only the latest complete frame', () => {
    const cloud = createEspPointCloud(makeFakeThree());

    cloud.update(framePoints(10, 1), 10, identityColor);
    assert.equal(cloud.object.geometry.drawRange.count, 10);

    cloud.update(framePoints(15, 2), 15, identityColor);
    assert.equal(cloud.object.geometry.drawRange.count, 15);

    const positions = cloud.object.geometry.getAttribute('position').array;
    assert.equal(Math.abs(positions[0]), 2);
    assert.equal(positions.length, 15 * 3);
});

test('ESP cloud displays a frame larger than the previous fixed limit', () => {
    const cloud = createEspPointCloud(makeFakeThree());

    cloud.update(framePoints(15, 3), 15, identityColor);

    assert.equal(cloud.object.geometry.drawRange.count, 15);
    assert.equal(cloud.object.geometry.getAttribute('position').array.length, 45);
});
