import numpy as np

from app.ingest import skeleton as sk
from app.ingest.reconstruct import normalize, orthonormal_basis, reconstruct


def test_normalize_produces_unit_vectors():
    v = np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0]])
    assert np.allclose(np.linalg.norm(normalize(v), axis=1), 1.0)


def test_normalize_survives_a_zero_vector():
    out = normalize(np.zeros((1, 3)))
    assert np.all(np.isfinite(out))
    assert np.isclose(np.linalg.norm(out), 1.0)


def test_orthonormal_basis_is_a_rotation_matrix():
    rng = np.random.default_rng(0)
    primary = rng.normal(size=(20, 3))
    reference = rng.normal(size=(20, 3))
    m = orthonormal_basis(primary, reference)
    eye = np.einsum("nij,nkj->nik", m, m)
    assert np.allclose(eye, np.eye(3), atol=1e-9)
    assert np.allclose(np.linalg.det(m), 1.0, atol=1e-9)


def test_orthonormal_basis_handles_a_parallel_reference():
    primary = np.array([[0.0, 1.0, 0.0]])
    m = orthonormal_basis(primary, primary.copy())
    assert np.all(np.isfinite(m))
    assert np.isclose(np.linalg.det(m)[0] if m.ndim == 3 else np.linalg.det(m), 1.0)


def test_every_bone_reconstructs(hello_take):
    motion = reconstruct(hello_take)
    assert len(motion) == len(sk.BONES)
    for bone in sk.BONES:
        bm = motion[bone.name]
        if bone.tail is None:
            assert bm.axis is None
            continue
        assert bm.axis.shape == (hello_take.frame_count, 3)
        assert np.allclose(np.linalg.norm(bm.axis, axis=1), 1.0)
        assert bm.length > 0.0
        if bone.twist == "frame":
            assert bm.basis is not None
            eye = np.einsum("nij,nkj->nik", bm.basis, bm.basis)
            assert np.allclose(eye, np.eye(3), atol=1e-9)


def test_hand_bone_axis_tracks_the_real_hand(hello_take):
    """Sanity: during a sign the dominant hand moves, so its bone axis must change."""
    motion = reconstruct(hello_take)
    axis = motion["RightHand"].axis
    spread = np.linalg.norm(axis - axis[0], axis=1).max()
    assert spread > 0.05
