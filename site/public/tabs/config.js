function leafType(value) {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (typeof value === 'string') return 'string';
  return 'json';
}

function leafValue(value, type) {
  return type === 'json' ? JSON.stringify(value) : value;
}

function buildFormTree(value, path = [], key = null) {
  if (Array.isArray(value)) {
    return {
      kind: 'row',
      path,
      key,
      children: value.map((item, index) => {
        const itemPath = path.concat(index);
        const type = leafType(item);
        return { kind: 'leaf', path: itemPath, type, value: leafValue(item, type) };
      }),
    };
  }

  if (value !== null && typeof value === 'object') {
    return {
      kind: 'group',
      path,
      key,
      children: Object.keys(value).map((childKey) => {
        const childPath = path.concat(childKey);
        return buildFormTree(value[childKey], childPath, childKey);
      }),
    };
  }

  const type = leafType(value);
  return { kind: 'leaf', path, type, value: leafValue(value, type) };
}

function cloneDeep(value) {
  if (Array.isArray(value)) return value.map(cloneDeep);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value)) out[k] = cloneDeep(value[k]);
    return out;
  }
  return value;
}

function applyEdit(root, path, rawValue) {
  const clone = cloneDeep(root);
  let node = clone;
  for (let i = 0; i < path.length - 1; i += 1) {
    node = node[path[i]];
  }
  node[path[path.length - 1]] = rawValue;
  return clone;
}

function initConfigTab(context) {
  const formEl = document.getElementById('config-form');
  const saveBtn = document.getElementById('config-save');
  const statusEl = document.getElementById('config-status');

  let working = null;

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = isError ? 'config-status config-status-error' : 'config-status config-status-ok';
  }

  function renderNode(node, container) {
    if (node.kind === 'group') {
      const group = document.createElement('fieldset');
      group.className = 'config-group';
      if (node.key) {
        const legend = document.createElement('legend');
        legend.textContent = node.key;
        group.appendChild(legend);
      }
      for (const child of node.children) {
        renderNode(child, group);
      }
      container.appendChild(group);
      return;
    }

    if (node.kind === 'row') {
      const row = document.createElement('div');
      row.className = 'config-row';
      const label = document.createElement('span');
      label.className = 'config-row-label';
      label.textContent = node.key;
      row.appendChild(label);
      for (const child of node.children) {
        renderNode(child, row);
      }
      container.appendChild(row);
      return;
    }

    const field = document.createElement('label');
    field.className = 'config-field';
    const labelText = document.createElement('span');
    labelText.textContent = node.path[node.path.length - 1];
    field.appendChild(labelText);

    const input = document.createElement('input');
    if (node.type === 'boolean') {
      input.type = 'checkbox';
      input.checked = node.value;
    } else if (node.type === 'number') {
      input.type = 'number';
      input.value = node.value;
    } else {
      input.type = 'text';
      input.value = node.value;
    }

    input.addEventListener('change', () => {
      let rawValue;
      if (node.type === 'boolean') rawValue = input.checked;
      else if (node.type === 'number') rawValue = Number(input.value);
      else if (node.type === 'json') rawValue = JSON.parse(input.value);
      else rawValue = input.value;

      working = applyEdit(working, node.path, rawValue);
    });

    field.appendChild(input);
    container.appendChild(field);
  }

  async function load() {
    const response = await fetch('/api/robot-config');
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setStatus(body.error || 'Nie udało się wczytać configu', true);
      return;
    }
    working = await response.json();
    formEl.textContent = '';
    renderNode(buildFormTree(working), formEl);
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const response = await fetch('/api/robot-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(working),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        setStatus('Zapisano', false);
      } else {
        setStatus(body.error || 'Błąd zapisu', true);
      }
    });
  }

  load();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { buildFormTree, applyEdit, initConfigTab };
}
