using NUnit.Framework;
using Signora.Retargeting;
using Signora.Tracking;
using UnityEngine;

namespace Signora.Tests
{
    public sealed class RetargeterCalibrationTests
    {
        private GameObject _root;

        [TearDown]
        public void TearDown()
        {
            if (_root != null) Object.DestroyImmediate(_root);
        }

        [Test]
        public void BodyCalibration_RequiresTorsoAndBothCompleteArms()
        {
            var body = BuildBodyRetargeter();
            var pose = BodyPose();
            Assert.That(body.Calibrate(pose, 0.45f), Is.True);
            Assert.That(body.CalibratedBindingCount, Is.EqualTo(body.BindingCount));

            pose.landmarks[16].confidence = 0f;
            Assert.That(body.Calibrate(pose, 0.45f), Is.False);
        }

        [Test]
        public void Recalibration_StillRestoresOriginalBindPose()
        {
            var body = BuildBodyRetargeter();
            var pose = BodyPose();
            Assert.That(body.Calibrate(pose, 0.45f), Is.True);
            var leftArm = _root.transform.Find("LeftArm");
            leftArm.localRotation = Quaternion.Euler(35f, 20f, -10f);

            Assert.That(body.Calibrate(pose, 0.45f), Is.True);
            body.BlendToBind(1f);
            Assert.That(Quaternion.Angle(Quaternion.identity, leftArm.localRotation), Is.LessThan(0.001f));
        }

        [Test]
        public void Hands_CalibrateIndependentlyAndDoNotBlockBody()
        {
            var body = BuildBodyRetargeter();
            BuildHandBones("Left");
            var rig = new AvatarRig(_root);
            var left = new HandRetargeter(rig, "Left");
            var right = new HandRetargeter(rig, "Right");

            Assert.That(body.Calibrate(BodyPose(), 0.45f), Is.True);
            Assert.That(left.Calibrate(Hand(), 0.45f), Is.True);
            Assert.That(right.Calibrate(Hand(), 0.45f), Is.False);
        }

        private BodyRetargeter BuildBodyRetargeter()
        {
            _root = new GameObject("Avatar");
            foreach (var name in new[] { "Spine2", "LeftArm", "LeftForeArm", "RightArm", "RightForeArm" })
            {
                var bone = new GameObject(name);
                bone.transform.SetParent(_root.transform, false);
            }
            return new BodyRetargeter(new AvatarRig(_root));
        }

        private void BuildHandBones(string side)
        {
            var hand = new GameObject($"{side}Hand");
            hand.transform.SetParent(_root.transform, false);
            foreach (var finger in new[] { "Thumb", "Index", "Middle", "Ring", "Pinky" })
            for (var segment = 1; segment <= 3; segment++)
            {
                var bone = new GameObject($"{side}Hand{finger}{segment}");
                bone.transform.SetParent(hand.transform, false);
            }
        }

        private static CanonicalPose BodyPose()
        {
            var pose = CanonicalTrackingFrameTests.ValidFrame().pose;
            pose.present = true;
            Set(pose.landmarks[11], -1f, 1f);
            Set(pose.landmarks[12], 1f, 1f);
            Set(pose.landmarks[13], -2f, 1f);
            Set(pose.landmarks[14], 2f, 1f);
            Set(pose.landmarks[15], -3f, 1f);
            Set(pose.landmarks[16], 3f, 1f);
            Set(pose.landmarks[23], -0.5f, -1f);
            Set(pose.landmarks[24], 0.5f, -1f);
            return pose;
        }

        private static CanonicalHand Hand()
        {
            var hand = CanonicalTrackingFrameTests.ValidFrame().leftHand;
            hand.present = true;
            hand.confidence = 1f;
            Set(hand.landmarks[0], 0f, 0f);
            var bases = new[] { 1, 5, 9, 13, 17 };
            for (var finger = 0; finger < bases.Length; finger++)
            for (var joint = 0; joint < 4; joint++)
                Set(hand.landmarks[bases[finger] + joint], (finger - 2) * 0.3f, 0.2f + joint * 0.3f);
            return hand;
        }

        private static void Set(CanonicalLandmark landmark, float x, float y)
        {
            landmark.x = x;
            landmark.y = y;
            landmark.z = 0.1f * y;
            landmark.confidence = 1f;
        }
    }
}
