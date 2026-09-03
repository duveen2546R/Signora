using NUnit.Framework;
using Signora.Retargeting;

namespace Signora.Tests
{
    public sealed class FaceRetargeterTests
    {
        [Test]
        public void RendererWeight_UsesImportedGlTFFrameRange()
        {
            Assert.That(FaceRetargeter.ToRendererWeight(0.75f, 1f), Is.EqualTo(0.75f).Within(0.0001f));
        }

        [Test]
        public void RendererWeight_StillSupportsNativeUnityHundredRange()
        {
            Assert.That(FaceRetargeter.ToRendererWeight(0.75f, 100f), Is.EqualTo(75f).Within(0.0001f));
        }

        [TestCase(-1f, 1f, 0f)]
        [TestCase(2f, 1f, 1f)]
        [TestCase(0.5f, -10f, 0f)]
        public void RendererWeight_ClampsUnsafeInputs(float normalized, float maximum, float expected)
        {
            Assert.That(FaceRetargeter.ToRendererWeight(normalized, maximum), Is.EqualTo(expected).Within(0.0001f));
        }
    }
}
