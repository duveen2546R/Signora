using System.Runtime.InteropServices;
using Signora.Tracking;
using UnityEngine;

namespace Signora.Retargeting
{
    public sealed class SignoraAvatarDriver : MonoBehaviour
    {
        private const float CalibrationDurationSeconds = 2f;
        // The browser supplies a generated, immutable avatar bind pose rather than noisy camera
        // inference. One accepted sample is therefore sufficient and keeps calibration reliable
        // when WebGL is hosted in a throttled/background pane that renders only a few frames during
        // the two-second window.
        private const int MinimumCalibrationSamples = 1;
        private const float HoldDurationSeconds = 0.2f;
        private const float NeutralBlendDurationSeconds = 0.5f;

        private readonly TrackingFrameFilter _filter = new TrackingFrameFilter();
        private readonly CalibrationFrameAccumulator _calibration = new CalibrationFrameAccumulator();
        private ITrackingSource _store;
        private AvatarRig _rig;
        private BodyRetargeter _body;
        private HandRetargeter _leftHand;
        private HandRetargeter _rightHand;
        private HeadRetargeter _head;
        private FaceRetargeter _face;
        private CanonicalTrackingFrameV1 _currentFrame;
        private int _lastAppliedSequence = -1;
        private float _calibrationStartedAt = float.NegativeInfinity;
        private bool _calibrating;
        private bool _bodyCalibrated;
        private bool _leftHandCalibrated;
        private bool _rightHandCalibrated;
        private bool _headCalibrated;

        public float MinimumLandmarkConfidence { get; set; } = 0.45f;
        public bool IsCalibrated => _bodyCalibrated;

        public void Initialize(GameObject avatarRoot, ITrackingSource store)
        {
            _store = store;
            _rig = new AvatarRig(avatarRoot);
            _body = new BodyRetargeter(_rig);
            _leftHand = new HandRetargeter(_rig, "Left");
            _rightHand = new HandRetargeter(_rig, "Right");
            _head = new HeadRetargeter(_rig);
            _face = new FaceRetargeter(_rig);
            Debug.Log($"Signora: rig ready with {_face.MappedBlendshapeCount} named blendshape mappings.");
        }

        public void BeginCalibration()
        {
            _calibrating = true;
            _calibrationStartedAt = Time.realtimeSinceStartup;
            _calibration.Reset();
            ReportCalibration("calibrating");
        }

        private void LateUpdate()
        {
            if (_store == null || _rig == null) return;
            if (_store.TryGetLatest(out var latest) && latest.sequence > _lastAppliedSequence)
            {
                _currentFrame = _filter.Filter(latest, Time.realtimeSinceStartup);
                _lastAppliedSequence = latest.sequence;
                if (_calibrating) _calibration.Add(_currentFrame, MinimumLandmarkConfidence);
            }

            if (_calibrating && Time.realtimeSinceStartup - _calibrationStartedAt >= CalibrationDurationSeconds)
            {
                CompleteCalibration();
            }
            if (_currentFrame == null || !_bodyCalibrated) return;

            var now = Time.realtimeSinceStartup;
            ApplyOrNeutralize(_bodyCalibrated, now - _store.LastPoseTime,
                () => _body.Apply(_currentFrame.pose, MinimumLandmarkConfidence), _body.BlendToBind);
            ApplyOrNeutralize(_leftHandCalibrated, now - _store.LastLeftHandTime,
                () => _leftHand.Apply(_currentFrame.leftHand, MinimumLandmarkConfidence), _leftHand.BlendToBind);
            ApplyOrNeutralize(_rightHandCalibrated, now - _store.LastRightHandTime,
                () => _rightHand.Apply(_currentFrame.rightHand, MinimumLandmarkConfidence), _rightHand.BlendToBind);

            var headAge = Mathf.Min(now - _store.LastFaceTime, now - _store.LastPoseTime);
            ApplyOrNeutralize(_headCalibrated, headAge,
                () => _head.Apply(_currentFrame.face, _currentFrame.pose, MinimumLandmarkConfidence), _head.BlendToBind);

            var faceAge = now - _store.LastFaceTime;
            if (faceAge <= HoldDurationSeconds) _face.Apply(_currentFrame.face);
            else _face.BlendToNeutral(NeutralStep(faceAge));
        }

        private void CompleteCalibration()
        {
            _calibrating = false;
            var pose = _calibration.BuildPose(MinimumCalibrationSamples);
            var leftHand = _calibration.BuildLeftHand(MinimumCalibrationSamples);
            var rightHand = _calibration.BuildRightHand(MinimumCalibrationSamples);
            var face = _calibration.BuildFace(MinimumCalibrationSamples);

            _bodyCalibrated = _body.Calibrate(pose, MinimumLandmarkConfidence);
            _leftHandCalibrated = _leftHand.Calibrate(leftHand, MinimumLandmarkConfidence);
            _rightHandCalibrated = _rightHand.Calibrate(rightHand, MinimumLandmarkConfidence);
            _headCalibrated = _head.Calibrate(face, pose, MinimumLandmarkConfidence);

            var state = !_bodyCalibrated ? "failed-body" :
                _leftHandCalibrated && _rightHandCalibrated ? "complete" :
                _leftHandCalibrated || _rightHandCalibrated ? "partial-hand" : "body-only";
            Debug.Log($"Signora: calibration {state}; samples={_calibration.SampleCount}, " +
                      $"body={_body.CalibratedBindingCount}/{_body.BindingCount}, " +
                      $"leftHand={_leftHand.CalibratedBindingCount}/{_leftHand.BindingCount}, " +
                      $"rightHand={_rightHand.CalibratedBindingCount}/{_rightHand.BindingCount}, head={_headCalibrated}.");
            ReportCalibration(state);
        }

        private static void ApplyOrNeutralize(bool calibrated, float age, System.Action apply, System.Action<float> neutralize)
        {
            if (!calibrated) return;
            if (age <= HoldDurationSeconds) apply();
            else neutralize(NeutralStep(age));
        }

        private static float NeutralStep(float age)
        {
            var elapsed = age - HoldDurationSeconds;
            if (elapsed >= NeutralBlendDurationSeconds) return 1f;
            var remaining = Mathf.Max(Time.deltaTime, NeutralBlendDurationSeconds - elapsed);
            return Mathf.Clamp01(Time.deltaTime / remaining);
        }

        private static void ReportCalibration(string state)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            Signora_ReportCalibration(state);
#else
            Debug.Log($"Signora calibration: {state}");
#endif
        }

#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")]
        private static extern void Signora_ReportCalibration(string state);
#endif
    }
}
