import numpy as np

from src.hardware.respeaker.respeaker import NoiseProfileReducer

SAMPLE_RATE = 16000
CHUNK = 1024


def _tone(freq_hz: float, n_samples: int, amplitude: float = 5000.0) -> np.ndarray:
    t = np.arange(n_samples) / SAMPLE_RATE
    return (np.sin(2 * np.pi * freq_hz * t) * amplitude).astype(np.int16)


def _noise(n_samples: int, amplitude: float = 3000.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n_samples) * amplitude).astype(np.int16)


def test_process_passes_through_unchanged_while_calibrating():
    reducer = NoiseProfileReducer(SAMPLE_RATE, CHUNK)
    reducer.start_calibration()

    chunk = _tone(300.0, CHUNK)
    out = reducer.process(chunk)

    np.testing.assert_array_equal(out.astype(np.int16), chunk)
    assert reducer.is_calibrating
    assert not reducer.has_profile


def test_stop_calibration_without_samples_leaves_no_profile():
    reducer = NoiseProfileReducer(SAMPLE_RATE, CHUNK)
    reducer.start_calibration()
    reducer.stop_calibration()

    assert not reducer.has_profile
    assert not reducer.is_calibrating


def test_calibration_builds_a_profile_that_gets_used():
    reducer = NoiseProfileReducer(SAMPLE_RATE, CHUNK, buffer_chunks=2)

    reducer.start_calibration()
    for _ in range(3):
        reducer.process(_noise(CHUNK))
    reducer.stop_calibration()

    assert reducer.has_profile
    assert not reducer.is_calibrating


def test_process_returns_silence_until_buffer_fills_then_emits_chunks():
    reducer = NoiseProfileReducer(SAMPLE_RATE, CHUNK, buffer_chunks=2)
    reducer.start_calibration()
    reducer.process(_noise(CHUNK))
    reducer.stop_calibration()

    # First chunk after calibration doesn't fill the 2-chunk process buffer
    # yet, so it must not leak unfiltered noise through - silence instead.
    first_out = reducer.process(_noise(CHUNK, seed=1))
    assert first_out.shape == (CHUNK,)
    np.testing.assert_array_equal(first_out, np.zeros(CHUNK, dtype=np.float32))

    # Second chunk completes the buffer - now we should get real output.
    second_out = reducer.process(_noise(CHUNK, seed=2))
    assert second_out.shape == (CHUNK,)


def test_reset_profile_clears_state():
    reducer = NoiseProfileReducer(SAMPLE_RATE, CHUNK, buffer_chunks=2)
    reducer.start_calibration()
    reducer.process(_noise(CHUNK))
    reducer.stop_calibration()
    assert reducer.has_profile

    reducer.reset_profile()

    assert not reducer.has_profile
    # Without a profile, process() is a passthrough again.
    chunk = _tone(300.0, CHUNK)
    out = reducer.process(chunk)
    np.testing.assert_allclose(out, chunk, atol=1e-3)
