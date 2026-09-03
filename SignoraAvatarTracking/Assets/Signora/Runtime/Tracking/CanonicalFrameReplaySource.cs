using System;
using UnityEngine;

namespace Signora.Tracking
{
    [Serializable]
    public sealed class CanonicalTrackingRecording
    {
        public CanonicalTrackingFrameV1[] frames = Array.Empty<CanonicalTrackingFrameV1>();
        public float framesPerSecond = 30f;
    }

    /// <summary>
    /// Deterministic tracking source for Editor debugging and recorded regression fixtures.
    /// The TextAsset JSON must contain a CanonicalTrackingRecording wrapper.
    /// </summary>
    public sealed class CanonicalFrameReplaySource : MonoBehaviour, ITrackingSource
    {
        [SerializeField] private TextAsset recordingJson;
        [SerializeField] private bool loop = true;
        [SerializeField] private bool playOnEnable = true;

        private readonly TrackingFrameStore _store = new TrackingFrameStore();
        private CanonicalTrackingRecording _recording;
        private float _startedAt;
        private int _publishedIndex = -1;
        private bool _playing;

        public float LastReceiptTime => _store.LastReceiptTime;
        public float LastPoseTime => _store.LastPoseTime;
        public float LastLeftHandTime => _store.LastLeftHandTime;
        public float LastRightHandTime => _store.LastRightHandTime;
        public float LastFaceTime => _store.LastFaceTime;

        public bool TryGetLatest(out CanonicalTrackingFrameV1 frame) => _store.TryGetLatest(out frame);

        private void OnEnable()
        {
            if (recordingJson == null) return;
            _recording = JsonUtility.FromJson<CanonicalTrackingRecording>(recordingJson.text);
            if (playOnEnable) Play();
        }

        public void Play()
        {
            _startedAt = Time.realtimeSinceStartup;
            _publishedIndex = -1;
            _playing = _recording?.frames != null && _recording.frames.Length > 0;
        }

        private void Update()
        {
            if (!_playing) return;
            var frameRate = Mathf.Max(1f, _recording.framesPerSecond);
            var elapsedIndex = Mathf.FloorToInt((Time.realtimeSinceStartup - _startedAt) * frameRate);
            if (loop) elapsedIndex %= _recording.frames.Length;
            else if (elapsedIndex >= _recording.frames.Length)
            {
                _playing = false;
                return;
            }
            if (elapsedIndex == _publishedIndex) return;
            _publishedIndex = elapsedIndex;
            var frame = _recording.frames[elapsedIndex];
            frame.sequence = Mathf.Max(frame.sequence, elapsedIndex + 1);
            _store.TryPublish(frame, out _);
        }
    }
}
