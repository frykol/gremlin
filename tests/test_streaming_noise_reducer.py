import numpy as np

from src.hardware.respeaker.interface import AudioFilterConfig
from src.hardware.respeaker.respeaker import StreamingNoiseReducer

SAMPLE_RATE = 16000
CHUNK = 1024


def _tone(freq_hz: float, n_samples: int, sample_rate: int = SAMPLE_RATE, amplitude: float = 10000.0) -> np.ndarray:
    t = np.arange(n_samples) / sample_rate
    return (np.sin(2 * np.pi * freq_hz * t) * amplitude).astype(np.int16)


def test_streaming_across_chunks_matches_continuous_filtering():
    """Filtering the signal chunk-by-chunk (as get_audio_chunk does) must
    match filtering it in one continuous call, since sosfilt keeps state
    (zi) across apply() calls - this is what fixes the chunk-boundary
    artifacts the old per-chunk sosfiltfilt produced."""
    reducer_streaming = StreamingNoiseReducer(SAMPLE_RATE)
    reducer_continuous = StreamingNoiseReducer(SAMPLE_RATE)

    n_chunks = 6
    full_signal = _tone(1000.0, CHUNK * n_chunks)

    streamed_out = np.concatenate([
        reducer_streaming.apply(full_signal[i * CHUNK:(i + 1) * CHUNK])
        for i in range(n_chunks)
    ])
    continuous_out = reducer_continuous.apply(full_signal)

    np.testing.assert_allclose(streamed_out, continuous_out, atol=1e-4)


def test_default_config_matches_original_hardcoded_bands():
    config = AudioFilterConfig()

    assert config.lidar_center_hz - config.lidar_width_hz / 2 == 150.0
    assert config.lidar_center_hz + config.lidar_width_hz / 2 == 235.0
    assert config.motor_center_hz - config.motor_width_hz / 2 == 360.0
    assert config.motor_center_hz + config.motor_width_hz / 2 == 470.0


def test_disabling_a_band_removes_its_attenuation():
    enabled = StreamingNoiseReducer(SAMPLE_RATE)
    disabled = StreamingNoiseReducer(SAMPLE_RATE)
    disabled.update_config(AudioFilterConfig(lidar_enabled=False, motor_enabled=False))

    tone = _tone(200.0, CHUNK)

    out_enabled = enabled.apply(tone)
    out_disabled = disabled.apply(tone)

    rms_enabled = np.sqrt(np.mean(out_enabled.astype(np.float64) ** 2))
    rms_disabled = np.sqrt(np.mean(out_disabled.astype(np.float64) ** 2))

    assert rms_disabled > rms_enabled * 5


def test_narrowing_band_preserves_more_signal_energy_near_center():
    wide = StreamingNoiseReducer(SAMPLE_RATE)
    narrow = StreamingNoiseReducer(SAMPLE_RATE)
    narrow.update_config(AudioFilterConfig(lidar_width_hz=10.0, motor_width_hz=10.0))

    # 300 Hz sits inside the wide lidar/motor gap but outside a narrowed band.
    tone = _tone(300.0, CHUNK)

    out_wide = wide.apply(tone)
    out_narrow = narrow.apply(tone)

    rms_wide = np.sqrt(np.mean(out_wide.astype(np.float64) ** 2))
    rms_narrow = np.sqrt(np.mean(out_narrow.astype(np.float64) ** 2))

    assert rms_narrow >= rms_wide


def test_zero_width_does_not_raise_degenerate_band_error():
    """Regression: the UI slider allowed width_hz down to 0, which made
    low == high in _build_sos and scipy.signal.butter raised
    'ValueError: Wn[0] must be less than Wn[1]'. That exception used to
    escape all the way up and kill CommandProcessor.process_commands()
    for good (see sim.log evidence) - here we just confirm the reducer
    itself no longer builds a degenerate band."""
    reducer = StreamingNoiseReducer(SAMPLE_RATE)
    reducer.update_config(AudioFilterConfig(lidar_width_hz=0.0, motor_width_hz=0.0))

    reducer.apply(_tone(200.0, CHUNK))  # must not raise


def test_negative_width_does_not_raise_degenerate_band_error():
    reducer = StreamingNoiseReducer(SAMPLE_RATE)
    reducer.update_config(AudioFilterConfig(lidar_width_hz=-5.0, motor_width_hz=-5.0))

    reducer.apply(_tone(200.0, CHUNK))  # must not raise
