const ENCODER_NAMES = ['FL', 'FR', 'RL', 'RR'];

function initEncodersTab(context) {
  const grid = document.getElementById('encoders-grid');
  const resetBtn = document.getElementById('encoders-reset');

  const valueEls = {};

  for (const name of ENCODER_NAMES) {
    const card = document.createElement('div');
    card.className = 'encoder-card';

    const label = document.createElement('div');
    label.className = 'encoder-label';
    label.textContent = name;

    const value = document.createElement('div');
    value.className = 'encoder-value';
    value.textContent = '0';

    card.appendChild(label);
    card.appendChild(value);
    grid.appendChild(card);

    valueEls[name] = value;
  }

  context.onControlMessage((data) => {
    if (data.type !== 'encoder_ticks') return;
    const ticks = data.ticks || {};
    for (const name of ENCODER_NAMES) {
      if (name in ticks && valueEls[name]) {
        valueEls[name].textContent = String(ticks[name]);
      }
    }
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      context.sendControl({ type: 'reset_encoders' });
    });
  }

  let pollTimer = null;
  pollTimer = setInterval(() => {
    context.sendControl({ type: 'get_encoder_ticks' });
  }, 200);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ENCODER_NAMES, initEncodersTab };
}
