using Signora.Retargeting;
using UnityEngine;

namespace Signora.Tracking
{
    public sealed class WebGLTrackingReceiver : MonoBehaviour
    {
        private readonly TrackingFrameStore _store = new TrackingFrameStore();
        private SignoraAvatarDriver _driver;
        private float _lastWarningTime = float.NegativeInfinity;
        private bool _loggedFirstFrame;

        public TrackingFrameStore Store => _store;

        public void Initialize(SignoraAvatarDriver driver)
        {
            _driver = driver;
        }

        // Called by the browser using UnityInstance.SendMessage.
        public void ReceiveFrame(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return;
            try
            {
                var frame = JsonUtility.FromJson<CanonicalTrackingFrameV1>(json);
                if (!_store.TryPublish(frame, out var error)) WarnThrottled($"{error} Rejected frames: {_store.RejectedFrameCount}.");
                else if (!_loggedFirstFrame)
                {
                    _loggedFirstFrame = true;
                    Debug.Log($"Signora: accepted first tracking frame (sequence {frame.sequence}).");
                }
            }
            catch (System.Exception exception)
            {
                WarnThrottled($"Could not parse tracking frame: {exception.Message}");
            }
        }

        // Called by the browser calibration button.
        public void BeginCalibration()
        {
            _driver?.BeginCalibration();
        }

        private void WarnThrottled(string message)
        {
            if (Time.realtimeSinceStartup - _lastWarningTime < 2f) return;
            _lastWarningTime = Time.realtimeSinceStartup;
            Debug.LogWarning($"Signora: {message}");
        }
    }
}
