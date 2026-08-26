const ADS1115_CHANNELS = ['a0', 'a1', 'a2', 'a3'];

// Backend (ADS1115.read_channels) already converts the raw ADC reading to
// the real voltage upstream of the divider (via PRZELICZNIK), so the value
// received here needs no further scaling.
function scaleAds1115Voltage(raw) {
  return raw;
}

function percentFromRange(value, min, max) {
  if (max === min) return 0;
  const pct = ((value - min) / (max - min)) * 100;
  return Math.min(100, Math.max(0, pct));
}

function initAds1115Tab(context) {
  const grid = document.getElementById('ads1115-grid');
  if (!grid) return;

  const rawEls = {};
  const valueEls = {};
  let percentEl = null;
  let percentRange = { min_volts: 0, max_volts: 1 };

  for (const channel of ADS1115_CHANNELS) {
    const card = document.createElement('div');
    card.className = 'encoder-card';

    const label = document.createElement('div');
    label.className = 'encoder-label';
    label.textContent = channel.toUpperCase();

    const raw = document.createElement('div');
    raw.className = 'ads1115-raw';
    raw.textContent = '0.000 V';

    const value = document.createElement('div');
    value.className = 'encoder-value';
    value.textContent = '0.00 V';

    card.appendChild(label);
    card.appendChild(raw);
    card.appendChild(value);

    if (channel === 'a0') {
      percentEl = document.createElement('div');
      percentEl.className = 'ads1115-percent';
      percentEl.textContent = '0%';
      card.appendChild(percentEl);
    }

    grid.appendChild(card);

    rawEls[channel] = raw;
    valueEls[channel] = value;
  }

  fetch('/api/robot-config')
    .then((response) => (response.ok ? response.json() : null))
    .then((config) => {
      const range = config && config.ads1115 && config.ads1115.a0_percent_range;
      if (range) percentRange = range;
    })
    .catch(() => {});

  context.onControlMessage((data) => {
    if (data.type !== 'ads1115_values') return;
    const values = data.values || {};
    for (const channel of ADS1115_CHANNELS) {
      if (channel in values && valueEls[channel]) {
        const scaled = scaleAds1115Voltage(values[channel]);
        valueEls[channel].textContent = `${scaled.toFixed(2)} V`;

        const rawKey = `raw_${channel}`;
        if (rawKey in values && rawEls[channel]) {
          rawEls[channel].textContent = `${values[rawKey].toFixed(3)} V`;
        }

        if (channel === 'a0' && percentEl) {
          const pct = percentFromRange(scaled, percentRange.min_volts, percentRange.max_volts);
          percentEl.textContent = `${pct.toFixed(0)}%`;
        }
      }
    }
  });

  setInterval(() => {
    context.sendControl({ type: 'get_ads1115_values' });
  }, 200);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { ADS1115_CHANNELS, scaleAds1115Voltage, percentFromRange, initAds1115Tab };
}
