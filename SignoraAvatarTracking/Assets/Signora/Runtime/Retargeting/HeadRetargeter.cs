using Signora.Tracking;
using UnityEngine;

namespace Signora.Retargeting
{
    public sealed class HeadRetargeter
    {
        private static readonly Matrix4x4 AxisConversion = Matrix4x4.Scale(new Vector3(1f, -1f, -1f));
        private readonly Transform _neck;
        private readonly Transform _head;
        private readonly Quaternion _neckBindLocal;
        private readonly Quaternion _headBindLocal;
        private readonly Quaternion _neckRestWorld;
        private readonly Quaternion _headRestWorld;
        private Quaternion _referenceFace;
        private Quaternion _referencePose;
        private bool _faceCalibrated;
        private bool _poseCalibrated;

        public HeadRetargeter(AvatarRig rig)
        {
            if (rig.TryGetBone("Neck", out var neck))
            {
                _neck = neck;
                _neckBindLocal = _neck.localRotation;
                _neckRestWorld = _neck.rotation;
            }
            if (rig.TryGetBone("Head", out var head))
            {
                _head = head;
                _headBindLocal = _head.localRotation;
                _headRestWorld = _head.rotation;
            }
        }

        public bool Calibrate(CanonicalFace face, CanonicalPose pose, float minimumConfidence)
        {
            _faceCalibrated = TryFaceRotation(face, out _referenceFace);
            _poseCalibrated = TryPoseRotation(pose, minimumConfidence, out _referencePose);
            return (_neck != null || _head != null) && (_faceCalibrated || _poseCalibrated);
        }

        public void Apply(CanonicalFace face, CanonicalPose pose, float minimumConfidence)
        {
            Quaternion delta;
            if (_faceCalibrated && TryFaceRotation(face, out var faceRotation))
            {
                delta = faceRotation * Quaternion.Inverse(_referenceFace);
            }
            else if (_poseCalibrated && TryPoseRotation(pose, minimumConfidence, out var poseRotation))
            {
                delta = poseRotation * Quaternion.Inverse(_referencePose);
            }
            else return;

            if (_neck != null)
            {
                var target = Quaternion.Slerp(Quaternion.identity, delta, 0.3f) * _neckRestWorld;
                _neck.rotation = RetargetingMath.SmoothWorldRotation(_neck, target, 12f, 360f);
            }
            if (_head != null)
            {
                var target = Quaternion.Slerp(Quaternion.identity, delta, 0.7f) * _headRestWorld;
                _head.rotation = RetargetingMath.SmoothWorldRotation(_head, target, 15f, 540f);
            }
        }

        public void BlendToBind(float amount)
        {
            amount = Mathf.Clamp01(amount);
            if (_neck != null) _neck.localRotation = Quaternion.Slerp(_neck.localRotation, _neckBindLocal, amount);
            if (_head != null) _head.localRotation = Quaternion.Slerp(_head.localRotation, _headBindLocal, amount);
        }

        public static bool TryFaceRotation(CanonicalFace face, out Quaternion rotation)
        {
            rotation = Quaternion.identity;
            if (face == null || !face.present || face.transform == null || face.transform.Length != 16) return false;
            var source = Matrix4x4.zero;
            for (var column = 0; column < 4; column++)
            {
                for (var row = 0; row < 4; row++)
                {
                    var value = face.transform[column * 4 + row];
                    if (!float.IsFinite(value)) return false;
                    source[row, column] = value;
                }
            }
            var converted = AxisConversion * source * AxisConversion;
            var forward = (Vector3)converted.GetColumn(2);
            var up = (Vector3)converted.GetColumn(1);
            if (forward.sqrMagnitude < 1e-6f || up.sqrMagnitude < 1e-6f) return false;
            forward.Normalize();
            up = Vector3.ProjectOnPlane(up, forward).normalized;
            if (up.sqrMagnitude < 1e-6f) return false;
            rotation = Quaternion.LookRotation(forward, up);
            return true;
        }

        public static bool TryPoseRotation(CanonicalPose pose, float minimumConfidence, out Quaternion rotation)
        {
            rotation = Quaternion.identity;
            if (pose == null || !pose.present ||
                !RetargetingMath.TryPoint(pose.landmarks, 7, minimumConfidence, out var leftEar) ||
                !RetargetingMath.TryPoint(pose.landmarks, 8, minimumConfidence, out var rightEar) ||
                !RetargetingMath.TryPoint(pose.landmarks, 0, minimumConfidence, out var nose)) return false;
            var lateral = leftEar - rightEar;
            if (lateral.sqrMagnitude < 1e-6f) return false;
            lateral.Normalize();
            var midpoint = (leftEar + rightEar) * 0.5f;
            var forward = Vector3.ProjectOnPlane(nose - midpoint, lateral);
            if (forward.sqrMagnitude < 1e-6f) return false;
            forward.Normalize();
            var up = Vector3.Cross(forward, lateral).normalized;
            if (up.sqrMagnitude < 1e-6f) return false;
            rotation = Quaternion.LookRotation(forward, up);
            return true;
        }
    }
}
