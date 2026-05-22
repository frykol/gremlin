import json
import base64
import asyncio

from src.dev_connection.interface import WSClientInterface
from src.robot_state import RobotState

class AudioStreamer:
    def __init__(self, ws: WSClientInterface, state: RobotState, channel: int = 0):
        self.ws: WSClientInterface = ws
        self.state: RobotState = state
        self.channel: int = channel
        self._last_sent_chunk_id: int = -1

    async def run(self):
        while True:
            if self.state.audio_stream_enabled:
                await self.send_audio_chunk()

            await asyncio.sleep(0.002)

    async def send_audio_chunk(self):
        chunk = self.state.last_audio_chunk

        if chunk is None or chunk.chunk_id == self._last_sent_chunk_id:
            return

        self._last_sent_chunk_id = chunk.chunk_id

        samples = chunk.samples

        if samples.ndim == 1:
            mono = samples
        else:
            ch = min(self.channel, samples.shape[1] - 1)
            mono = samples[:, ch]

        pcm_base64 = base64.b64encode(mono.astype("int16").tobytes()).decode("utf-8")

        await self.ws.send(json.dumps({
            "type": "audio_chunk",
            "samples": pcm_base64,
            "timestamp": chunk.timestamp,
            "sample_rate": chunk.sample_rate,
            "channels": 1,
            "chunk_id": chunk.chunk_id,
            "source_channel": self.channel,
        }))
