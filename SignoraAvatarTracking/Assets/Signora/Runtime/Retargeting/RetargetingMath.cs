using Signora.Tracking;
using UnityEngine;

namespace Signora.Retargeting
{
    public static class RetargetingMath
    {
        public static bool TryDirection(CanonicalLandmark[] landmarks, int from, int to, float minimumConfidence, out Vector3 direction)
        {
            direction = Vector3.forward;
            if (!TryPoint(landmarks, from, minimumConfidence, out var start) ||
                !TryPoint(landmarks, to, minimumConfidence, out var end)) return false;
            var delta = end - start;
            if (delta.sqrMagnitude < 1e-8f) return false;
            direction = delta.normalized;
            return true;
        }

        public static bool TryPoint(CanonicalLandmark[] landmarks, int index, float minimumConfidence, out Vector3 position)
        {
            position = Vector3.zero;
            if (landmarks == null || index < 0 || index >= landmarks.Length) return false;
            var point = landmarks[index];
            if (point == null || point.confidence < minimumConfidence) return false;
            position = point.Position;
            return IsFinite(position);
        }

        public static bool TryBasis(
            CanonicalLandmark[] landmarks,
            int origin,
            int rightIndex,
            int upIndex,
            float minimumConfidence,
            out Quaternion basis)
        {
            basis = Quaternion.identity;
            if (!TryPoint(landmarks, origin, minimumConfidence, out var center) ||
                !TryPoint(landmarks, rightIndex, minimumConfidence, out var rightPoint) ||
                !TryPoint(landmarks, upIndex, minimumConfidence, out var upPoint)) return false;
            var right = (rightPoint - center).normalized;
            var upSeed = (upPoint - center).normalized;
            var forward = Vector3.Cross(right, upSeed);
            if (right.sqrMagnitude < 0.99f || forward.sqrMagnitude < 1e-6f) return false;
            var up = Vector3.Cross(forward.normalized, right).normalized;
            basis = Quaternion.LookRotation(forward.normalized, up);
            return true;
        }

        public static Quaternion SmoothWorldRotation(Transform bone, Quaternion target, float response, float maximumDegreesPerSecond)
        {
            var interpolation = 1f - Mathf.Exp(-Mathf.Max(0.01f, response) * Time.deltaTime);
            var smoothed = Quaternion.Slerp(bone.rotation, target, interpolation);
            return Quaternion.RotateTowards(bone.rotation, smoothed, maximumDegreesPerSecond * Time.deltaTime);
        }

        private static bool IsFinite(Vector3 value)
        {
            return float.IsFinite(value.x) && float.IsFinite(value.y) && float.IsFinite(value.z);
        }
    }

    internal sealed class DirectionBoneBinding
    {
        private readonly Transform _bone;
        private readonly int _from;
        private readonly int _to;
        private readonly Quaternion _bindLocalRotation;
        private readonly Quaternion _restWorldRotation;
        private Vector3 _referenceDirection;
        private Quaternion _bindWorldRotation;
        private bool _calibrated;

        public DirectionBoneBinding(Transform bone, int from, int to)
        {
            _bone = bone;
            _from = from;
            _to = to;
            _bindLocalRotation = bone.localRotation;
            _restWorldRotation = bone.rotation;
        }

        public bool IsCalibrated => _calibrated;

        public bool Calibrate(CanonicalLandmark[] landmarks, float minimumConfidence)
        {
            if (!RetargetingMath.TryDirection(landmarks, _from, _to, minimumConfidence, out _referenceDirection)) return false;
            // Always map the user's reference pose to the avatar's original rest pose. Using
            // the bone's current rotation makes a second calibration inherit the old motion
            // offset and progressively twists the rig.
            _bindWorldRotation = _restWorldRotation;
            _calibrated = true;
            return true;
        }

        public void Apply(CanonicalLandmark[] landmarks, float minimumConfidence, float response, float maximumDegreesPerSecond)
        {
            if (!_calibrated || !RetargetingMath.TryDirection(landmarks, _from, _to, minimumConfidence, out var current)) return;
            var delta = Quaternion.FromToRotation(_referenceDirection, current);
            var target = delta * _bindWorldRotation;
            _bone.rotation = RetargetingMath.SmoothWorldRotation(_bone, target, response, maximumDegreesPerSecond);
        }

        public void BlendToBind(float amount)
        {
            _bone.localRotation = Quaternion.Slerp(_bone.localRotation, _bindLocalRotation, Mathf.Clamp01(amount));
        }
    }

    internal sealed class BasisBoneBinding
    {
        private readonly Transform _bone;
        private readonly int _origin;
        private readonly int _right;
        private readonly int _up;
        private readonly Quaternion _bindLocalRotation;
        private readonly Quaternion _restWorldRotation;
        private Quaternion _referenceBasis;
        private Quaternion _bindWorldRotation;
        private bool _calibrated;

        public BasisBoneBinding(Transform bone, int origin, int right, int up)
        {
            _bone = bone;
            _origin = origin;
            _right = right;
            _up = up;
            _bindLocalRotation = bone.localRotation;
            _restWorldRotation = bone.rotation;
        }

        public bool IsCalibrated => _calibrated;

        public bool Calibrate(CanonicalLandmark[] landmarks, float minimumConfidence)
        {
            if (!RetargetingMath.TryBasis(landmarks, _origin, _right, _up, minimumConfidence, out _referenceBasis)) return false;
            _bindWorldRotation = _restWorldRotation;
            _calibrated = true;
            return true;
        }

        public void Apply(CanonicalLandmark[] landmarks, float minimumConfidence, float response, float maximumDegreesPerSecond)
        {
            if (!_calibrated || !RetargetingMath.TryBasis(landmarks, _origin, _right, _up, minimumConfidence, out var currentBasis)) return;
            var delta = currentBasis * Quaternion.Inverse(_referenceBasis);
            var target = delta * _bindWorldRotation;
            _bone.rotation = RetargetingMath.SmoothWorldRotation(_bone, target, response, maximumDegreesPerSecond);
        }

        public void BlendToBind(float amount)
        {
            _bone.localRotation = Quaternion.Slerp(_bone.localRotation, _bindLocalRotation, Mathf.Clamp01(amount));
        }
    }
}
