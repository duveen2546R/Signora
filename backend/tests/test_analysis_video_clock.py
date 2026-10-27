import numpy as np
import pytest

from app.services.analysis_worker import video_window
from app.validation.mixed_effects import ValidationError


def test_full_clip_uses_decoded_clock_instead_of_nominal_frame_duration():
    assert video_window(np.array([0, 5.333])) == [0, 5.333]
    assert video_window(np.array([0.012, 5.32])) == [0.012, 5.32]


def test_submillisecond_boundary_rounding_is_clipped_but_clock_errors_are_rejected():
    assert video_window(np.array([0, 5.333]), [0, 128 / 24]) == [0, 5.333]
    assert video_window(np.array([0, 5.333]), [0.5, 5]) == [0.5, 5]
    with pytest.raises(ValidationError, match="decoded landmark clock"):
        video_window(np.array([0, 5.333]), [0, 5.334])
    with pytest.raises(ValidationError, match="no decoded samples"):
        video_window(np.array([0, 5.333]), [5.3331, 5.3332])
