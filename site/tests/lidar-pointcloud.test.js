const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { createPointCloud } = require(
    path.join(__dirname, '..', 'public', 'lidar', 'js', 'pointcloud.js')
);

// Minimalna atrapa THREE - pointcloud.js uzywa tylko BufferGeometry,
// BufferAttribute, PointsMaterial i Points, wiec nie potrzeba prawdziwego
// three.min.js (ani WebGL) do przetestowania logiki bufora pierscieniowego.
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

function framePoints(n, value = 1) {
    // x,y,z,intensity na punkt
    const arr = new Float32Array(n * 4);
    for (let i = 0; i < n; i++) {
        arr[i * 4 + 0] = value;
        arr[i * 4 + 1] = value;
        arr[i * 4 + 2] = value;
        arr[i * 4 + 3] = 150;
    }
    return arr;
}

test('ring buffer accumulates points across frames', () => {
    const cloud = createPointCloud(makeFakeThree(), 100);

    cloud.update(framePoints(10), 10, identityColor);
    assert.equal(cloud.object.geometry.drawRange.count, 10);

    cloud.update(framePoints(15), 15, identityColor);
    assert.equal(cloud.object.geometry.drawRange.count, 25);
});

test('ring buffer wraps and caps at maxPoints', () => {
    const cloud = createPointCloud(makeFakeThree(), 20);

    cloud.update(framePoints(30), 30, identityColor);

    // Nigdy wiecej niz maxPoints.
    assert.equal(cloud.object.geometry.drawRange.count, 20);
});

test('empty scan frame clears the cloud instead of freezing it', () => {
    // Regresja: backend CELOWO wysyla pusta chmure, gdy zrodlo danych
    // padnie (backend/lidar/app.py - "zeby frontend pokazal pusty stan, a
    // nie stara chmure w nieskonczonosc"). Frontend przy pointCount=0 nie
    // wchodzil do petli, wiec filledCount zostawal - chmura zamarzala i
    // wygladala na zywa. Dokladnie stan "wyglada, ze dziala, a nie dziala",
    // ktorego spec zabrania.
    const cloud = createPointCloud(makeFakeThree(), 100);
    cloud.update(framePoints(30), 30, identityColor);
    assert.equal(cloud.object.geometry.drawRange.count, 30);

    cloud.update(new Float32Array(0), 0, identityColor);

    assert.equal(
        cloud.object.geometry.drawRange.count,
        0,
        'pusta ramka musi wyczyscic chmure, a nie zostawic stara'
    );
});

test('cloud refills correctly after being cleared', () => {
    // Po wyczyszczeniu kursor zapisu musi wrocic do zera - inaczej nowe
    // punkty ladowalyby w srodku bufora, a drawRange pokazywalby smieci
    // z poczatku tablicy.
    const cloud = createPointCloud(makeFakeThree(), 100);
    cloud.update(framePoints(30, 1), 30, identityColor);
    cloud.update(new Float32Array(0), 0, identityColor);

    cloud.update(framePoints(5, 7), 5, identityColor);

    assert.equal(cloud.object.geometry.drawRange.count, 5);
    const pos = cloud.object.geometry.getAttribute('position').array;
    // Pierwszy punkt musi pochodzic z NOWEJ ramki (wartosc 7 po rotacji,
    // wiec na pewno nie 0 i nie z poprzedniej ramki o wartosci 1).
    const firstMagnitude = Math.abs(pos[0]) + Math.abs(pos[1]) + Math.abs(pos[2]);
    assert.ok(firstMagnitude > 5, `pierwszy slot nie zawiera nowej ramki: ${firstMagnitude}`);
});
