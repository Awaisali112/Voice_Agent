# edge_tts_plugin.py
from __future__ import annotations

import io
import uuid
import numpy as np
import edge_tts
import soundfile as sf

from livekit.agents import tts
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS



class EdgeTTS(tts.TTS):
    def __init__(
        self,
        *,
        voice: str = "en-US-AriaNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        sample_rate: int = 24000,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._pitch = pitch
        self._sample_rate = sample_rate

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "EdgeTTSStream":
        return EdgeTTSStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
            pitch=self._pitch,
            sample_rate=self._sample_rate,
        )


class EdgeTTSStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: EdgeTTS,
        input_text: str,
        conn_options: APIConnectOptions,
        voice: str,
        rate: str,
        volume: str,
        pitch: str,
        sample_rate: int,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._pitch = pitch
        self._sample_rate = sample_rate

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        # Collect all MP3 chunks from edge-tts
        mp3_buf = io.BytesIO()
        communicate = edge_tts.Communicate(
            text=self._input_text,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
            pitch=self._pitch,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])

        mp3_buf.seek(0)
        if mp3_buf.getbuffer().nbytes == 0:
            return

        # Decode MP3 → float32 numpy, then resample to target rate
        audio_np, source_rate = sf.read(mp3_buf, dtype="float32")

        # Resample if needed
        if source_rate != self._sample_rate:
            import librosa
            audio_np = librosa.resample(
                audio_np, orig_sr=source_rate, target_sr=self._sample_rate
            )

        # Stereo → mono if needed
        if audio_np.ndim == 2:
            audio_np = audio_np.mean(axis=1)

        # Float32 → int16 PCM
        audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

        import uuid
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=self._sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(audio_int16.tobytes())
        output_emitter.flush()