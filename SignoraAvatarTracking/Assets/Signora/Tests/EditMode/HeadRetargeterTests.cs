using NUnit.Framework;
using Signora.Retargeting;
using Signora.Tracking;
using UnityEngine;

namespace Signora.Tests
{
    public sealed class HeadRetargeterTests
    {
        [TestCase(25f, 0f, 0f)]
        [TestCase(0f, -20f, 0f)]
        [TestCase(0f, 0f, 15f)]
        public void FaceMatrix_ConvertsKnownEulerRotation(float pitch, float yaw, float roll)
        {
            var expected = Quaternion.Euler(pitch, yaw, roll);
            var conversion = Matrix4x4.Scale(new Vector3(1f, -1f, -1f));
            var unityMatrix = Matrix4x4.Rotate(expected);
            var mediaPipeMatrix = conversion * unityMatrix * conversion;
            var face = new CanonicalFace { present = true, transform = ColumnMajor(mediaPipeMatrix) };

            Assert.That(HeadRetargeter.TryFaceRotation(face, out var actual), Is.True);
            Assert.That(Quaternion.Angle(expected, actual), Is.LessThan(0.01f));
        }

        [Test]
        public void PoseFallback_UsesEarsAndNoseAsStableBasis()
        {
            var pose = CanonicalTrackingFrameTests.ValidFrame().pose;
            pose.present = true;
            Set(pose.landmarks[7], new Vector3(1f, 0f, 0f));
            Set(pose.landmarks[8], new Vector3(-1f, 0f, 0f));
            Set(pose.landmarks[0], new Vector3(0f, 0f, 1f));

            Assert.That(HeadRetargeter.TryPoseRotation(pose, 0.45f, out var rotation), Is.True);
            Assert.That(Quaternion.Angle(Quaternion.identity, rotation), Is.LessThan(0.01f));
        }

        private static float[] ColumnMajor(Matrix4x4 matrix)
        {
            var result = new float[16];
            for (var column = 0; column < 4; column++)
            for (var row = 0; row < 4; row++) result[column * 4 + row] = matrix[row, column];
            return result;
        }

        private static void Set(CanonicalLandmark landmark, Vector3 value)
        {
            landmark.x = value.x;
            landmark.y = value.y;
            landmark.z = value.z;
            landmark.confidence = 1f;
        }
    }
}
