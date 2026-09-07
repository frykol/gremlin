function initSpeakerTab(context) {
  const soundsList = document.getElementById('speaker-sounds-list');
  const loadingEl = document.getElementById('speaker-loading');
  const noSoundsEl = document.getElementById('speaker-no-sounds');
  const stopBtn = document.getElementById('speaker-stop');
  const statusText = document.getElementById('speaker-status-text');
  const danceSelect = document.getElementById('speaker-dance-select');

  let currentlyPlaying = null;
  let danceMusicTimer = null;

  // Common sound files to look for
  const commonSounds = [
    'bark.mp3',
    'alert.mp3',
    'beep.mp3',
    'bark.wav',
    'alert.wav',
    'beep.wav',
  ];

  // Fallback used only if the control tab (which owns the real list) hasn't
  // exposed window.robotDance yet - keeps the select from being empty.
  const fallbackDances = {
    bujanie: 'Bujanie',
    krok: 'Krok w bok',
    zygzak: 'Zygzak',
    szal: 'Szał',
    spinjitsu: 'Spinjitsu',
  };

  function updateStatus(message, isPlaying = false) {
    statusText.textContent = message;
    statusText.classList.toggle('status-playing', isPlaying);
    statusText.classList.toggle('status-disconnected', !isPlaying);
  }

  const VOLUME_STORAGE_PREFIX = 'speaker-volume:';

  function getVolume(fileName) {
    const stored = localStorage.getItem(VOLUME_STORAGE_PREFIX + fileName);
    const percent = stored === null ? 100 : Number(stored);
    return Number.isFinite(percent) ? percent : 100;
  }

  function setVolume(fileName, percent) {
    localStorage.setItem(VOLUME_STORAGE_PREFIX + fileName, String(percent));
  }

  function playSound(fileName) {
    const filePath = `sounds/${fileName}`;
    context.sendControl({
      type: 'play_sound',
      file: filePath,
      volume: getVolume(fileName) / 100,
    });
    currentlyPlaying = fileName;
    updateStatus(`Odtwarzanie: ${fileName}`, true);
  }

  function stopSound() {
    context.sendControl({
      type: 'stop_sound',
    });
    currentlyPlaying = null;
    updateStatus('Zatrzymano', false);
  }

  function stopDanceMusic() {
    if (danceMusicTimer) {
      clearTimeout(danceMusicTimer);
      danceMusicTimer = null;
    }
    if (window.robotDance) {
      window.robotDance.stop();
    }
  }

  function stopAll() {
    stopDanceMusic();
    stopSound();
  }

  // Loads just enough of the audio file to know its length, without
  // audibly playing it in the browser (playback itself happens on the
  // robot's speaker via the play_sound control message).
  function getSoundDuration(fileName) {
    return new Promise((resolve) => {
      const audio = new Audio(`sounds/${fileName}`);
      audio.preload = 'metadata';

      const fallbackMs = 8000;
      const timeoutId = setTimeout(() => resolve(fallbackMs), 3000);

      audio.addEventListener('loadedmetadata', () => {
        clearTimeout(timeoutId);
        const seconds = Number.isFinite(audio.duration) ? audio.duration : fallbackMs / 1000;
        resolve(Math.max(seconds, 1) * 1000);
      });
      audio.addEventListener('error', () => {
        clearTimeout(timeoutId);
        resolve(fallbackMs);
      });
    });
  }

  function danceToSound(fileName) {
    const danceName = danceSelect.value;
    if (!danceName || !window.robotDance) return;

    stopAll();
    playSound(fileName);
    window.robotDance.start(danceName, { loop: true });

    getSoundDuration(fileName).then((durationMs) => {
      if (currentlyPlaying !== fileName) return; // superseded by a newer action
      danceMusicTimer = setTimeout(() => {
        danceMusicTimer = null;
        stopDanceMusic();
        stopSound();
      }, durationMs);
    });
  }

  function populateDanceSelect() {
    const dances = (window.robotDance && window.robotDance.DANCES) || null;
    danceSelect.innerHTML = '';

    if (dances) {
      Object.entries(dances).forEach(([key, dance]) => {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = dance.label;
        danceSelect.appendChild(opt);
      });
    } else {
      Object.entries(fallbackDances).forEach(([key, label]) => {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = label;
        danceSelect.appendChild(opt);
      });
    }
  }

  function buildSoundRow(soundFile) {
    const row = document.createElement('div');
    row.className = 'sound-row';

    const playBtn = document.createElement('button');
    playBtn.className = 'sound-button';
    playBtn.textContent = soundFile;
    playBtn.addEventListener('click', () => playSound(soundFile));

    const danceBtn = document.createElement('button');
    danceBtn.className = 'sound-dance-button';
    danceBtn.textContent = '🕺 Tańcz';
    danceBtn.title = 'Zatańcz do tego utworu';
    danceBtn.addEventListener('click', () => danceToSound(soundFile));

    const volumeRow = document.createElement('div');
    volumeRow.className = 'sound-volume';

    const volumeSlider = document.createElement('input');
    volumeSlider.type = 'range';
    volumeSlider.min = '0';
    volumeSlider.max = '100';
    volumeSlider.value = String(getVolume(soundFile));

    const volumeValue = document.createElement('span');
    volumeValue.className = 'sound-volume-value';
    volumeValue.textContent = `${volumeSlider.value}%`;

    volumeSlider.addEventListener('input', () => {
      volumeValue.textContent = `${volumeSlider.value}%`;
      setVolume(soundFile, Number(volumeSlider.value));
    });

    volumeRow.appendChild(volumeSlider);
    volumeRow.appendChild(volumeValue);

    row.appendChild(playBtn);
    row.appendChild(danceBtn);
    row.appendChild(volumeRow);
    return row;
  }

  function loadSounds() {
    loadingEl.style.display = 'block';
    soundsList.innerHTML = '';
    noSoundsEl.style.display = 'none';

    // Fetch list of available sounds from backend
    fetch('/api/sounds')
      .then((res) => res.json())
      .then((data) => {
        loadingEl.style.display = 'none';

        if (!data.sounds || data.sounds.length === 0) {
          noSoundsEl.style.display = 'block';
          return;
        }

        data.sounds.forEach((soundFile) => {
          soundsList.appendChild(buildSoundRow(soundFile));
        });
      })
      .catch((err) => {
        console.error('Failed to load sounds:', err);
        loadingEl.style.display = 'none';

        // Fallback: show hardcoded common sounds
        console.log('Using fallback sound list');
        commonSounds.forEach((soundFile) => {
          soundsList.appendChild(buildSoundRow(soundFile));
        });
      });
  }

  stopBtn.addEventListener('click', stopAll);

  populateDanceSelect();

  // Load sounds when tab is initialized
  loadSounds();

  // Listen for control messages about playback status
  context.onControlMessage((data) => {
    if (data.type === 'speaker_status') {
      if (data.is_playing) {
        updateStatus(`Odtwarzanie: ${data.file}`, true);
      } else {
        updateStatus('Gotowy', false);
        currentlyPlaying = null;
      }
    }
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { initSpeakerTab };
}
