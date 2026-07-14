const GPIO_PINS = {
  7: 'GPIO4',
  11: 'GPIO17',
  13: 'GPIO27',
  15: 'GPIO22',
  16: 'GPIO23',
  18: 'GPIO24',
  22: 'GPIO25',
  29: 'GPIO5',
  31: 'GPIO6',
  32: 'GPIO12',
  33: 'GPIO13',
  36: 'GPIO16',
  37: 'GPIO26',
};

function initGpioTab(context) {
  const grid = document.getElementById('gpio-grid');
  const set0Btn = document.getElementById('gpio-set-0');
  const set1Btn = document.getElementById('gpio-set-1');

  const buttons = {};
  const values = {};
  let activePin = null;

  for (let pin = 1; pin <= 40; pin++) {
    const label = GPIO_PINS[pin] || String(pin);
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.disabled = !GPIO_PINS[pin];

    if (GPIO_PINS[pin]) {
      values[pin] = 0;
      btn.addEventListener('click', () => {
        activePin = pin;
        Object.values(buttons).forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      });
    }

    buttons[pin] = btn;
    grid.appendChild(btn);
    updateButtonColor(pin);
  }

  function updateButtonColor(pin) {
    if (!GPIO_PINS[pin]) return;
    buttons[pin].style.background = values[pin] === 1 ? '#00ff00' : '#ff3333';
  }

  function setValue(value) {
    if (activePin === null) return;
    values[activePin] = value;
    updateButtonColor(activePin);
    context.sendControl({ type: 'gpio', pin_name: GPIO_PINS[activePin], value });
  }

  set0Btn.addEventListener('click', () => setValue(0));
  set1Btn.addEventListener('click', () => setValue(1));
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { GPIO_PINS, initGpioTab };
}
