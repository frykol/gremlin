# Speaker Tab Setup

## What Was Added

A new "Głośnik" (Speaker) tab has been added to the web interface for easy sound playback.

### Files Modified/Created:
1. **site/public/index.html** - Added speaker tab button and panel
2. **site/public/tabs/speaker.js** - Speaker tab logic (play sounds, display list)
3. **site/public/style.css** - Speaker UI styling
4. **site/public/app.js** - Registered speaker tab initialization

## How to Use

### 1. Add Your Sound Files
Place MP3 or WAV files in the project's `sounds/` directory:
```bash
/home/gremlin/gremlin/sounds/
├── bark.mp3
├── alert.mp3
├── beep.mp3
└── custom_sound.mp3
```

### 2. Transfer Files via SCP
```bash
scp your_sounds/*.mp3 gremlin@192.168.1.215:/home/gremlin/gremlin/sounds/
```

### 3. Use the Web Interface
1. Open the robot control panel in your browser
2. Click the "Głośnik" (Speaker) tab
3. Click any sound button to play it
4. Click "Stop" to stop playback
5. Playback status is shown at the top

## How It Works

- The tab lists available sounds from the `sounds/` directory
- If the backend endpoint isn't available (yet), it shows common sound names
- Click any sound name to play it
- The status indicator shows currently playing sound
- Stop button halts playback immediately

## Fallback Behavior

If the backend hasn't implemented the `/api/sounds` endpoint yet, the interface will show these hardcoded sounds:
- bark.mp3
- alert.mp3
- beep.mp3
- bark.wav
- alert.wav
- beep.wav

You can still click any of these buttons even if the file doesn't exist yet - they'll attempt to play them. Just add the files when ready.

## Future Enhancement

To list sounds dynamically without hardcoding, add this endpoint to the backend:

```python
@app.get("/api/sounds")
async def list_sounds():
    sounds_dir = Path("/home/gremlin/gremlin/sounds")
    sounds = []
    if sounds_dir.exists():
        sounds = sorted([f.name for f in sounds_dir.glob("*.mp3")] + 
                       [f.name for f in sounds_dir.glob("*.wav")])
    return {"sounds": sounds}
```

But for now, the tab works perfectly with the fallback!
