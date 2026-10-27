using NUnit.Framework;
using Signora.Tracking;

namespace Signora.Tests
{
    public sealed class TrackingFrameStoreTests
    {
        [Test]
        public void EmptyFrame_DoesNotRefreshChannelFreshness()
        {
            var store = new TrackingFrameStore();
            var visible = CanonicalTrackingFrameTests.ValidFrame();
            visible.pose.present = true;
            Assert.That(store.TryPublish(visible, out var error), Is.True, error);
            var poseTime = store.LastPoseTime;

            var empty = CanonicalTrackingFrameTests.ValidFrame();
            empty.sequence = 2;
            empty.pose.present = false;
            empty.face.present = true;
            Assert.That(store.TryPublish(empty, out error), Is.True, error);

            Assert.That(store.LastPoseTime, Is.EqualTo(poseTime));
            Assert.That(store.LastFaceTime, Is.GreaterThan(float.NegativeInfinity));
            Assert.That(store.LastReceiptTime, Is.GreaterThanOrEqualTo(poseTime));
        }

        [Test]
        public void HandFreshness_IsIndependentForEachSide()
        {
            var store = new TrackingFrameStore();
            var left = CanonicalTrackingFrameTests.ValidFrame();
            left.leftHand.present = true;
            Assert.That(store.TryPublish(left, out var error), Is.True, error);
            var leftTime = store.LastLeftHandTime;
            Assert.That(store.LastRightHandTime, Is.EqualTo(float.NegativeInfinity));

            var right = CanonicalTrackingFrameTests.ValidFrame();
            right.sequence = 2;
            right.rightHand.present = true;
            Assert.That(store.TryPublish(right, out error), Is.True, error);
            Assert.That(store.LastLeftHandTime, Is.EqualTo(leftTime));
            Assert.That(store.LastRightHandTime, Is.GreaterThan(float.NegativeInfinity));
        }
    }
}
