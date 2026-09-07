# I2S Speaker Implementation

## Overview
The robot now has I2S speaker support on GPIO pins 19 and 21 for playing WAV audio files (16-bit PCM).

## Configuration
In `config.json`, the speaker is configured under the `"speaker"` section:
```json
"speaker": {
  "gpio_pins": [19, 21],
  "is_dummy": false
}
```

- `gpio_pins`: SCK (Serial Clock) and SD (Serial Data) pins for I2S
- `is_dummy`: Set to `true` to use a mock speaker for testing (prints playback messages instead of playing audio)

## Usage

### Playing a Sound
Send a WebSocket command to trigger sound playback:

```json
{
  "type": "play_sound",
  "file": "/path/to/sound.wav"
}
```

### Example Use Cases
- Bark sound when robot detects obstacle: `"/mnt/sdcard/sounds/bark.mp3"` or `.wav`
- Alert tone on startup: `"/mnt/sdcard/sounds/alert.mp3"` or `.wav`
- Voice signal for command feedback: `"/mnt/sdcard/sounds/beep.mp3"` or `.wav`

## Audio Requirements
- **Formats**: MP3 or WAV (PCM)
- **Bit depth**: 16-bit
- **Sample rate**: Any (will play at the file's sample rate)
- **Channels**: Mono or stereo (stereo will use first channel)

### MP3 Support
MP3 playback requires `ffmpeg` to be installed on the system:
```bash
sudo apt-get install ffmpeg
```

## Implementation Details

### Files
- `src/hardware/speaker/interface.py` - Abstract speaker interface
- `src/hardware/speaker/i2s_speaker.py` - I2S implementation using `simpleaudio`
- `src/hardware/speaker/dummy_speaker.py` - Mock implementation for testing
- `src/hardware/speaker/factory.py` - Factory to create speaker instances

### Hardware Setup
The I2S device must be pre-configured at the system level (ALSA):
1. Configure device tree overlay or audio device mapping
2. Test with ALSA tools: `aplay -L` and `aplay -D <device> file.wav`
3. Once working, the robot will use that device

### Threading Model
Playback is non-blocking and runs in a background thread. Multiple play commands can be queued.

### State
Check playback state with:
```python
speaker.get_state()  # Returns: PlaybackState(is_playing, current_file, position)
```

## Testing
To test with dummy speaker (no hardware required):
1. Set `"is_dummy": true` in `config.json`
2. Send play_sound commands - you'll see console output like:
   ```
   [DummySpeaker] Playing: /path/to/sound.wav
   [DummySpeaker] Stopped: /path/to/sound.wav
   ```

## Troubleshooting

### No Sound on Hardware
- Verify I2S device is properly configured: `cat /proc/asound/cards`
- Test with system tools: `aplay /path/to/test.wav`
- Check pin configuration matches actual wiring
- Verify audio file format (MP3 or 16-bit PCM WAV)

### Import Errors
- Ensure required packages are installed: `pip install -r requirements.txt`
- For MP3 support, also install ffmpeg: `sudo apt-get install ffmpeg`

### MP3 Playback Issues
- Ensure ffmpeg is installed: `which ffmpeg`
- If ffmpeg is missing, `pydub` will fail to load MP3 files

### Audio Quality/Format Issues
- MP3 files are automatically converted to PCM at their native sample rate
- WAV files must be in 16-bit PCM format
- Both formats will be converted to mono for playback (stereo files use first channel)
