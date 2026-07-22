const test = require('node:test');
const assert = require('node:assert/strict');

const { buildFormTree, applyEdit } = require('../public/tabs/config');

test('buildFormTree builds a leaf node for a top-level boolean', () => {
  const tree = buildFormTree({ dev: true });
  assert.deepEqual(tree, {
    kind: 'group',
    path: [],
    key: null,
    children: [
      { kind: 'leaf', path: ['dev'], type: 'boolean', value: true },
    ],
  });
});

test('buildFormTree builds nested groups for nested objects', () => {
  const tree = buildFormTree({ gpio: { chip: '/dev/gpiochip0' } });
  assert.deepEqual(tree, {
    kind: 'group',
    path: [],
    key: null,
    children: [
      {
        kind: 'group',
        path: ['gpio'],
        key: 'gpio',
        children: [
          { kind: 'leaf', path: ['gpio', 'chip'], type: 'string', value: '/dev/gpiochip0' },
        ],
      },
    ],
  });
});

test('buildFormTree builds a row of leaves for an array of numbers', () => {
  const tree = buildFormTree({ encoders: { FL: [17, 27] } });
  const gpioGroup = tree.children[0];
  const row = gpioGroup.children[0];
  assert.deepEqual(row, {
    kind: 'row',
    path: ['encoders', 'FL'],
    key: 'FL',
    children: [
      { kind: 'leaf', path: ['encoders', 'FL', 0], type: 'number', value: 17 },
      { kind: 'leaf', path: ['encoders', 'FL', 1], type: 'number', value: 27 },
    ],
  });
});

test('buildFormTree falls back to json type for null', () => {
  const tree = buildFormTree({ nothing: null });
  assert.deepEqual(tree.children[0], { kind: 'leaf', path: ['nothing'], type: 'json', value: 'null' });
});

test('applyEdit overwrites a top-level scalar without touching siblings', () => {
  const root = { dev: true, is_custom: false };
  const result = applyEdit(root, ['dev'], false);
  assert.deepEqual(result, { dev: false, is_custom: false });
  assert.equal(root.dev, true, 'original object must not be mutated');
});

test('applyEdit overwrites a nested value', () => {
  const root = { gpio: { chip: '/dev/gpiochip0', pins: {} } };
  const result = applyEdit(root, ['gpio', 'chip'], '/dev/gpiochip1');
  assert.deepEqual(result, { gpio: { chip: '/dev/gpiochip1', pins: {} } });
});

test('applyEdit overwrites an array element by index', () => {
  const root = { encoders: { FL: [17, 27] } };
  const result = applyEdit(root, ['encoders', 'FL', 1], 99);
  assert.deepEqual(result, { encoders: { FL: [17, 99] } });
});

test('applyEdit never adds new keys', () => {
  const root = { dev: true };
  const result = applyEdit(root, ['dev'], false);
  assert.deepEqual(Object.keys(result), Object.keys(root));
});
