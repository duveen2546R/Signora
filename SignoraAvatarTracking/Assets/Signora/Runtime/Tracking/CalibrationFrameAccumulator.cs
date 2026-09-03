using System;
using UnityEngine;

namespace Signora.Tracking
{
    /// <summary>
    /// Averages only confident samples collected during the guided calibration window.
    /// Landmarks without enough observations are emitted with zero confidence, allowing the
    /// retargeters to make an explicit, per-binding readiness decision.
    /// </summary>
    public sealed class CalibrationFrameAccumulator
    {
        private readonly LandmarkAccumulator[] _pose = Create(CanonicalTrackingSchema.PoseLandmarkCount);
        private readonly LandmarkAccumulator[] _leftHand = Create(CanonicalTrackingSchema.HandLandmarkCount);
        private readonly LandmarkAccumulator[] _rightHand = Create(CanonicalTrackingSchema.HandLandmarkCount);
        private readonly float[] _faceTransformSum = new float[16];
        private int _poseFrames;
        private int _leftHandFrames;
        private int _rightHandFrames;
        private int _faceFrames;

        public int SampleCount { get; private set; }

        public void Reset()
        {
            Reset(_pose);
            Reset(_leftHand);
            Reset(_rightHand);
            Array.Clear(_faceTransformSum, 0, _faceTransformSum.Length);
            _poseFrames = 0;
            _leftHandFrames = 0;
            _rightHandFrames = 0;
            _faceFrames = 0;
            SampleCount = 0;
        }

        public void Add(CanonicalTrackingFrameV1 frame, float minimumConfidence)
        {
            if (frame == null) return;
            SampleCount++;
            if (frame.pose != null && frame.pose.present)
            {
                _poseFrames++;
                Add(frame.pose.landmarks, _pose, minimumConfidence);
            }
            if (frame.leftHand != null && frame.leftHand.present)
            {
                _leftHandFrames++;
                Add(frame.leftHand.landmarks, _leftHand, minimumConfidence);
            }
            if (frame.rightHand != null && frame.rightHand.present)
            {
                _rightHandFrames++;
                Add(frame.rightHand.landmarks, _rightHand, minimumConfidence);
            }
            if (frame.face != null && frame.face.present && IsFiniteTransform(frame.face.transform))
            {
                _faceFrames++;
                for (var index = 0; index < 16; index++) _faceTransformSum[index] += frame.face.transform[index];
            }
        }

        public CanonicalPose BuildPose(int minimumSamples)
        {
            var landmarks = Build(_pose, minimumSamples);
            return new CanonicalPose
            {
                present = _poseFrames >= minimumSamples,
                confidence = AverageConfidence(landmarks),
                landmarks = landmarks
            };
        }

        public CanonicalHand BuildLeftHand(int minimumSamples) => BuildHand(_leftHand, _leftHandFrames, "Left", minimumSamples);

        public CanonicalHand BuildRightHand(int minimumSamples) => BuildHand(_rightHand, _rightHandFrames, "Right", minimumSamples);

        public CanonicalFace BuildFace(int minimumSamples)
        {
            var transform = IdentityTransform();
            var present = _faceFrames >= minimumSamples;
            if (present)
            {
                for (var index = 0; index < transform.Length; index++) transform[index] = _faceTransformSum[index] / _faceFrames;
            }
            return new CanonicalFace
            {
                present = present,
                confidence = present ? 1f : 0f,
                transform = transform,
                blendshapes = Array.Empty<CanonicalBlendshape>()
            };
        }

        private static CanonicalHand BuildHand(LandmarkAccumulator[] source, int frameCount, string handedness, int minimumSamples)
        {
            var landmarks = Build(source, minimumSamples);
            return new CanonicalHand
            {
                present = frameCount >= minimumSamples,
                confidence = AverageConfidence(landmarks),
                handedness = handedness,
                landmarks = landmarks
            };
        }

        private static void Add(CanonicalLandmark[] landmarks, LandmarkAccumulator[] destination, float minimumConfidence)
        {
            if (landmarks == null || landmarks.Length != destination.Length) return;
            for (var index = 0; index < destination.Length; index++)
            {
                var point = landmarks[index];
                if (point == null || point.confidence < minimumConfidence || !IsFinite(point.Position)) continue;
                destination[index].Sum += point.Position;
                destination[index].ConfidenceSum += point.confidence;
                destination[index].Count++;
            }
        }

        private static CanonicalLandmark[] Build(LandmarkAccumulator[] source, int minimumSamples)
        {
            minimumSamples = Mathf.Max(1, minimumSamples);
            var result = new CanonicalLandmark[source.Length];
            for (var index = 0; index < source.Length; index++)
            {
                var sample = source[index];
                if (sample.Count >= minimumSamples)
                {
                    var average = sample.Sum / sample.Count;
                    result[index] = new CanonicalLandmark
                    {
                        x = average.x,
                        y = average.y,
                        z = average.z,
                        confidence = Mathf.Clamp01(sample.ConfidenceSum / sample.Count)
                    };
                }
                else result[index] = new CanonicalLandmark();
            }
            return result;
        }

        private static float AverageConfidence(CanonicalLandmark[] landmarks)
        {
            var sum = 0f;
            var count = 0;
            foreach (var point in landmarks)
            {
                if (point == null || point.confidence <= 0f) continue;
                sum += point.confidence;
                count++;
            }
            return count > 0 ? sum / count : 0f;
        }

        private static bool IsFiniteTransform(float[] transform)
        {
            if (transform == null || transform.Length != 16) return false;
            foreach (var value in transform)
            {
                if (!float.IsFinite(value)) return false;
            }
            return true;
        }

        private static bool IsFinite(Vector3 value) =>
            float.IsFinite(value.x) && float.IsFinite(value.y) && float.IsFinite(value.z);

        private static float[] IdentityTransform()
        {
            var transform = new float[16];
            for (var index = 0; index < 16; index += 5) transform[index] = 1f;
            return transform;
        }

        private static LandmarkAccumulator[] Create(int count)
        {
            var result = new LandmarkAccumulator[count];
            for (var index = 0; index < result.Length; index++) result[index] = new LandmarkAccumulator();
            return result;
        }

        private static void Reset(LandmarkAccumulator[] accumulators)
        {
            foreach (var accumulator in accumulators)
            {
                accumulator.Sum = Vector3.zero;
                accumulator.ConfidenceSum = 0f;
                accumulator.Count = 0;
            }
        }

        private sealed class LandmarkAccumulator
        {
            public Vector3 Sum;
            public float ConfidenceSum;
            public int Count;
        }
    }
}
