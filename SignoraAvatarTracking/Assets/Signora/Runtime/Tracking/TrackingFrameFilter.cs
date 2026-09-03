using System;
using UnityEngine;

namespace Signora.Tracking
{
    public sealed class TrackingFrameFilter
    {
        private readonly OneEuroVector3Filter[] _pose = Create(CanonicalTrackingSchema.PoseLandmarkCount, 1.15f, 0.07f);
        private readonly OneEuroVector3Filter[] _leftHand = Create(CanonicalTrackingSchema.HandLandmarkCount, 1.7f, 0.16f);
        private readonly OneEuroVector3Filter[] _rightHand = Create(CanonicalTrackingSchema.HandLandmarkCount, 1.7f, 0.16f);

        public CanonicalTrackingFrameV1 Filter(CanonicalTrackingFrameV1 frame, float time)
        {
            FilterLandmarks(frame.pose?.landmarks, _pose, time);
            FilterLandmarks(frame.leftHand?.landmarks, _leftHand, time);
            FilterLandmarks(frame.rightHand?.landmarks, _rightHand, time);
            return frame;
        }

        private static void FilterLandmarks(CanonicalLandmark[] landmarks, OneEuroVector3Filter[] filters, float time)
        {
            if (landmarks == null || landmarks.Length != filters.Length) return;
            for (var index = 0; index < landmarks.Length; index++)
            {
                var point = landmarks[index];
                if (point == null || point.confidence <= 0f) continue;
                var filtered = filters[index].Filter(point.Position, time);
                point.x = filtered.x;
                point.y = filtered.y;
                point.z = filtered.z;
            }
        }

        private static OneEuroVector3Filter[] Create(int count, float minimumCutoff, float beta)
        {
            var filters = new OneEuroVector3Filter[count];
            for (var index = 0; index < count; index++) filters[index] = new OneEuroVector3Filter(minimumCutoff, beta);
            return filters;
        }
    }
}

