using NUnit.Framework;
using Signora.Tracking;

namespace Signora.Tests
{
    public sealed class OneEuroFilterTests
    {
        [Test]
        public void ConstantInput_RemainsConstant()
        {
            var filter = new OneEuroFilter();
            Assert.That(filter.Filter(3.5f, 0f), Is.EqualTo(3.5f));
            Assert.That(filter.Filter(3.5f, 1f / 30f), Is.EqualTo(3.5f).Within(0.0001f));
        }

        [Test]
        public void StepInput_IsSmoothedWithoutOvershoot()
        {
            var filter = new OneEuroFilter(1f, 0.05f);
            filter.Filter(0f, 0f);
            var value = filter.Filter(1f, 1f / 30f);
            Assert.That(value, Is.GreaterThan(0f));
            Assert.That(value, Is.LessThan(1f));
        }
    }
}

