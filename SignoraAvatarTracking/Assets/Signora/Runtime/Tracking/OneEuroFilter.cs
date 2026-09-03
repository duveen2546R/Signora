using UnityEngine;

namespace Signora.Tracking
{
    public sealed class OneEuroFilter
    {
        private readonly float _minimumCutoff;
        private readonly float _beta;
        private readonly float _derivativeCutoff;
        private bool _initialized;
        private float _previousValue;
        private float _previousDerivative;
        private float _previousTime;

        public OneEuroFilter(float minimumCutoff = 1.2f, float beta = 0.08f, float derivativeCutoff = 1f)
        {
            _minimumCutoff = Mathf.Max(0.001f, minimumCutoff);
            _beta = Mathf.Max(0f, beta);
            _derivativeCutoff = Mathf.Max(0.001f, derivativeCutoff);
        }

        public float Filter(float value, float time)
        {
            if (!_initialized)
            {
                _initialized = true;
                _previousValue = value;
                _previousTime = time;
                return value;
            }

            var deltaTime = Mathf.Max(1f / 240f, time - _previousTime);
            var derivative = (value - _previousValue) / deltaTime;
            var filteredDerivative = Lerp(_previousDerivative, derivative, Alpha(deltaTime, _derivativeCutoff));
            var cutoff = _minimumCutoff + _beta * Mathf.Abs(filteredDerivative);
            var filtered = Lerp(_previousValue, value, Alpha(deltaTime, cutoff));

            _previousTime = time;
            _previousValue = filtered;
            _previousDerivative = filteredDerivative;
            return filtered;
        }

        public void Reset()
        {
            _initialized = false;
        }

        private static float Alpha(float deltaTime, float cutoff)
        {
            var tau = 1f / (2f * Mathf.PI * cutoff);
            return 1f / (1f + tau / deltaTime);
        }

        private static float Lerp(float from, float to, float alpha)
        {
            return from + alpha * (to - from);
        }
    }

    public sealed class OneEuroVector3Filter
    {
        private readonly OneEuroFilter _x;
        private readonly OneEuroFilter _y;
        private readonly OneEuroFilter _z;

        public OneEuroVector3Filter(float minimumCutoff, float beta)
        {
            _x = new OneEuroFilter(minimumCutoff, beta);
            _y = new OneEuroFilter(minimumCutoff, beta);
            _z = new OneEuroFilter(minimumCutoff, beta);
        }

        public Vector3 Filter(Vector3 value, float time)
        {
            return new Vector3(_x.Filter(value.x, time), _y.Filter(value.y, time), _z.Filter(value.z, time));
        }
    }
}

