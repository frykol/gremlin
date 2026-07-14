const I2C_LABELS = [
  'LP przód', 'LP tył',
  'LT przód', 'LT tył',
  'PP tył', 'PP przód',
  'PT tył', 'PT przód',
];

function pwmFromPercent(pct) {
  return Math.round(pct * 40.95);
}

function oppositeChannel(index) {
  return index ^ 1;
}

function initI2cTab(context) {
  const container = document.getElementById('i2c-buttons');
  const slider = document.getElementById('i2c-slider');

  const buttons = [];
  const values = new Array(8).fill(0);
  let activeIndex = 0;

  function sendMotor(channel, pwm) {
    context.sendControl({ type: 'motor', channel, pwm });
  }

  function updateButtonColor(index) {
    const v = values[index];
    const r = 255 - Math.round(v * 2.55);
    const g = Math.round(v * 2.55);
    buttons[index].style.background = `rgb(${r}, ${g}, 50)`;
  }

  I2C_LABELS.forEach((label, index) => {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      activeIndex = index;
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      slider.value = values[index];
    });
    buttons.push(btn);
    container.appendChild(btn);
    updateButtonColor(index);
  });

  slider.addEventListener('input', () => {
    const v = Number(slider.value);

    if (v > 0) {
      const opp = oppositeChannel(activeIndex);
      if (values[opp] > 0) {
        values[opp] = 0;
        updateButtonColor(opp);
        sendMotor(opp, 0);
      }
    }

    values[activeIndex] = v;
    updateButtonColor(activeIndex);
    sendMotor(activeIndex, pwmFromPercent(v));
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { pwmFromPercent, oppositeChannel, I2C_LABELS, initI2cTab };
}
