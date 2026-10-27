using UnityEngine;

namespace Signora.Tracking
{
    public interface ITrackingSource
    {
        float LastReceiptTime { get; }
        float LastPoseTime { get; }
        float LastLeftHandTime { get; }
        float LastRightHandTime { get; }
        float LastFaceTime { get; }
        bool TryGetLatest(out CanonicalTrackingFrameV1 frame);
    }

    public sealed class TrackingFrameStore : ITrackingSource
    {
        private CanonicalTrackingFrameV1 _latest;
        private int _lastSequence = -1;

        public float LastReceiptTime { get; private set; } = float.NegativeInfinity;
        public float LastPoseTime { get; private set; } = float.NegativeInfinity;
        public float LastLeftHandTime { get; private set; } = float.NegativeInfinity;
        public float LastRightHandTime { get; private set; } = float.NegativeInfinity;
        public float LastFaceTime { get; private set; } = float.NegativeInfinity;
        public int RejectedFrameCount { get; private set; }

        public bool TryPublish(CanonicalTrackingFrameV1 frame, out string error)
        {
            if (frame == null)
            {
                error = "Tracking frame was null.";
                RejectedFrameCount++;
                return false;
            }
            if (!frame.IsStructurallyValid(out error))
            {
                RejectedFrameCount++;
                return false;
            }
            if (frame.sequence <= _lastSequence)
            {
                error = $"Stale frame sequence {frame.sequence}.";
                RejectedFrameCount++;
                return false;
            }
            _latest = frame;
            _lastSequence = frame.sequence;
            var now = Time.realtimeSinceStartup;
            LastReceiptTime = now;
            // Empty inference results still arrive at camera rate. Track freshness per channel
            // so a visible face cannot keep a lost body frozen, and stale frames can return
            // every affected part to its bind pose instead of refreshing one global clock.
            if (frame.pose != null && frame.pose.present) LastPoseTime = now;
            if (frame.leftHand != null && frame.leftHand.present) LastLeftHandTime = now;
            if (frame.rightHand != null && frame.rightHand.present) LastRightHandTime = now;
            if (frame.face != null && frame.face.present) LastFaceTime = now;
            error = string.Empty;
            return true;
        }

        public bool TryGetLatest(out CanonicalTrackingFrameV1 frame)
        {
            frame = _latest;
            return frame != null;
        }
    }
}
