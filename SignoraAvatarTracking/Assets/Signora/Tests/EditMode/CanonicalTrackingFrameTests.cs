using NUnit.Framework;
using Signora.Tracking;

namespace Signora.Tests
{
    public sealed class CanonicalTrackingFrameTests
    {
        [Test]
        public void ValidFrame_AcceptsExpectedContract()
        {
            var frame = ValidFrame();
            Assert.That(frame.IsStructurallyValid(out var error), Is.True, error);
        }

        [Test]
        public void InvalidSchema_IsRejected()
        {
            var frame = ValidFrame();
            frame.schemaVersion = 9;
            Assert.That(frame.IsStructurallyValid(out var error), Is.False);
            Assert.That(error, Does.Contain("Unsupported"));
        }

        [Test]
        public void InvalidHandCount_IsRejected()
        {
            var frame = ValidFrame();
            frame.leftHand.landmarks = new CanonicalLandmark[20];
            Assert.That(frame.IsStructurallyValid(out var error), Is.False);
            Assert.That(error, Does.Contain("Hand"));
        }

        internal static CanonicalTrackingFrameV1 ValidFrame()
        {
            return new CanonicalTrackingFrameV1
            {
                schemaVersion = CanonicalTrackingSchema.Version,
                sequence = 1,
                captureTimeMs = 10,
                inferenceEndTimeMs = 20,
                pose = new CanonicalPose { landmarks = Points(CanonicalTrackingSchema.PoseLandmarkCount) },
                leftHand = new CanonicalHand { landmarks = Points(CanonicalTrackingSchema.HandLandmarkCount) },
                rightHand = new CanonicalHand { landmarks = Points(CanonicalTrackingSchema.HandLandmarkCount) },
                face = new CanonicalFace { transform = new float[16] }
            };
        }

        private static CanonicalLandmark[] Points(int count)
        {
            var points = new CanonicalLandmark[count];
            for (var index = 0; index < count; index++) points[index] = new CanonicalLandmark();
            return points;
        }
    }
}

