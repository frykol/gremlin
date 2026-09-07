const test = require('node:test');
const assert = require('node:assert/strict');

const { computeChannelValues, computeChannelValuesFromVector, recalcDirections, DANCES } = require('../public/tabs/control.js');

test('computeChannelValues drives front-left/front-right channels forward for Przód', () => {
  const values = computeChannelValues(new Set(['Przód']), 100);
  assert.equal(values[0], 100);
  assert.equal(values[1], 0);
  assert.equal(values[2], 100);
  assert.equal(values[3], 0);
  assert.equal(values[5], 100);
  assert.equal(values[4], 0);
  assert.equal(values[7], 100);
  assert.equal(values[6], 0);
});

test('computeChannelValues drives reverse channels for Tył', () => {
  const values = computeChannelValues(new Set(['Tył']), 50);
  assert.equal(values[1], 50);
  assert.equal(values[0], 0);
  assert.equal(values[3], 50);
  assert.equal(values[2], 0);
});

test('computeChannelValues is all-zero with no active directions', () => {
  const values = computeChannelValues(new Set(), 100);
  for (let i = 0; i < 8; i++) {
    assert.equal(values[i], 0);
  }
});

test('computeChannelValuesFromVector drives forward channels for positive vy', () => {
  const values = computeChannelValuesFromVector(1, 0, 0, 100);
  const forward = computeChannelValues(new Set(['Przód']), 100);
  assert.deepEqual(values, forward);
});

test('computeChannelValuesFromVector drives reverse channels for negative vy', () => {
  const values = computeChannelValuesFromVector(-1, 0, 0, 100);
  const reverse = computeChannelValues(new Set(['Tył']), 100);
  assert.deepEqual(values, reverse);
});

test('computeChannelValuesFromVector strafes right for positive vx', () => {
  const values = computeChannelValuesFromVector(0, 1, 0, 100);
  const strafeRight = computeChannelValues(new Set(['Full prawo']), 100);
  assert.deepEqual(values, strafeRight);
});

test('computeChannelValuesFromVector rotates right for positive omega', () => {
  const values = computeChannelValuesFromVector(0, 0, 1, 100);
  const rotateRight = computeChannelValues(new Set(['Prawo']), 100);
  assert.deepEqual(values, rotateRight);
});

test('computeChannelValuesFromVector is all-zero for a zero vector', () => {
  const values = computeChannelValuesFromVector(0, 0, 0, 100);
  for (let i = 0; i < 8; i++) {
    assert.equal(values[i], 0);
  }
});

test('computeChannelValuesFromVector combines vy and omega proportionally (turning right while driving forward slows the left side, speeds the right side)', () => {
  const values = computeChannelValuesFromVector(1, 0, 0.5, 100);
  assert.equal(values[0], 0);
  assert.equal(values[1], 50);
  assert.equal(values[2], 0);
  assert.equal(values[3], 100);
});

test('recalcDirections maps arrow keys to direction names', () => {
  const dirs = recalcDirections(new Set(), new Set(['Up']));
  assert.ok(dirs.has('Przód'));
});

test('recalcDirections maps Shift+Left to Full lewo instead of Lewo', () => {
  const dirs = recalcDirections(new Set(), new Set(['Left', 'Shift']));
  assert.ok(dirs.has('Full lewo'));
  assert.ok(!dirs.has('Lewo'));
});

test('recalcDirections includes pressed buttons unchanged', () => {
  const dirs = recalcDirections(new Set(['Prawo']), new Set());
  assert.ok(dirs.has('Prawo'));
});

test('DANCES defines exactly 5 dances, each with valid steps', () => {
  const names = Object.keys(DANCES);
  assert.equal(names.length, 5);

  const validDirections = new Set(['Przód', 'Tył', 'Prawo', 'Lewo', 'Full lewo', 'Full prawo']);

  for (const name of names) {
    const dance = DANCES[name];
    assert.ok(dance.label);
    assert.ok(dance.powerPct > 0 && dance.powerPct <= 100);
    assert.ok(Array.isArray(dance.steps) && dance.steps.length > 0);
    for (const step of dance.steps) {
      assert.ok(Array.isArray(step.dirs));
      for (const dir of step.dirs) {
        assert.ok(validDirections.has(dir), `unknown direction ${dir} in dance ${name}`);
      }
      assert.ok(step.ms > 0);
      if (step.powerPct != null) {
        assert.ok(step.powerPct > 0 && step.powerPct <= 100);
      }
    }
  }
});

test('spinjitsu ramps power logarithmically from 10% to 100% while rotating in place', () => {
  const steps = DANCES.spinjitsu.steps;
  assert.equal(steps[0].powerPct, 8);
  assert.equal(steps[steps.length - 1].powerPct, 65);
  for (const step of steps) {
    assert.deepEqual(step.dirs, ['Prawo']);
  }

  // Moc rośnie monotonicznie (niemalejąco - zaokrąglenia mogą dać płaskie odcinki).
  for (let i = 1; i < steps.length; i++) {
    assert.ok(steps[i].powerPct >= steps[i - 1].powerPct);
  }

  // Krzywa logarytmiczna: przyrost mocy w pierwszej połowie kroków większy
  // niż w drugiej połowie (szybki start, spowolnienie pod koniec).
  const mid = Math.floor(steps.length / 2);
  const firstHalfGain = steps[mid].powerPct - steps[0].powerPct;
  const secondHalfGain = steps[steps.length - 1].powerPct - steps[mid].powerPct;
  assert.ok(firstHalfGain > secondHalfGain);
});

test('spinjitsu spins longer than the original 9-step version', () => {
  const steps = DANCES.spinjitsu.steps;
  const totalMs = steps.reduce((sum, step) => sum + step.ms, 0);
  assert.ok(totalMs > 2250);
});
