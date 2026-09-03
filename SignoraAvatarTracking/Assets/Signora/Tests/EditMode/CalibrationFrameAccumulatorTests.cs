using NUnit.Framework;
using Signora.Tracking;

namespace Signora.Tests
{
    public sealed class CalibrationFrameAccumulatorTests
    {
        [Test]
        public void BuildPose_AveragesConfidentSamples()
        {
            var accumulator = new CalibrationFrameAccumulator();
            for (var sample = 0; sample < 6; sample++)
            {
                var frame = CanonicalTrackingFrameTests.ValidFrame();
                frame.pose.present = true;
                frame.pose.landmarks[11].x = sample;
                frame.pose.landmarks[11].confidence = 1f;
                accumulator.Add(frame, 0.45f);
            }

            var pose = accumulator.BuildPose(6);
            Assert.That(pose.present, Is.True);
            Assert.That(pose.landmarks[11].x, Is.EqualTo(2.5f).Within(0.0001f));
            Assert.That(pose.landmarks[11].confidence, Is.EqualTo(1f));
        }

        [Test]
        public void BuildPose_RejectsLandmarksWithInsufficientCoverage()
        {
            var accumulator = new CalibrationFrameAccumulator();
            for (var sample = 0; sample < 5; sample++)
            {
                var frame = CanonicalTrackingFrameTests.ValidFrame();
                frame.pose.present = true;
                frame.pose.landmarks[11].confidence = 1f;
                accumulator.Add(frame, 0.45f);
            }

            Assert.That(accumulator.BuildPose(6).landmarks[11].confidence, Is.Zero);
        }

        [Test]
        public void MissingHands_DoNotPreventPoseAccumulation()
        {
            var accumulator = new CalibrationFrameAccumulator();
            for (var sample = 0; sample < 6; sample++)
            {
                var frame = CanonicalTrackingFrameTests.ValidFrame();
                frame.pose.present = true;
                frame.leftHand.present = false;
                frame.rightHand.present = false;
                accumulator.Add(frame, 0.45f);
            }

            Assert.That(accumulator.BuildPose(6).present, Is.True);
            Assert.That(accumulator.BuildLeftHand(6).present, Is.False);
            Assert.That(accumulator.BuildRightHand(6).present, Is.False);
        }
    }
}
