// Plays a queue of signs as one sentence.
//
// A sentence is not a slideshow of clips: without a transition between signs the avatar snaps
// between poses and the result is unreadable. Each gap is cross-faded over a duration proportional
// to how far apart the two poses actually are, so small hand moves stay tight and big ones get the
// time they need.

using System.Collections.Generic;
using UnityEngine;

namespace SignSure
{
    public sealed class SignSequencer : MonoBehaviour
    {
        public SignPlayer player;

        [Tooltip("Still frames held at the end of each sign, in seconds.")]
        public float holdSeconds = 0.12f;

        public float minTransition = 0.12f;
        public float maxTransition = 0.30f;

        public System.Action<string> OnSignStarted;
        public System.Action OnSequenceFinished;

        readonly Queue<(SignClip clip, string gloss)> _queue = new();
        Quaternion[] _blendFrom;
        float _blendDuration;
        float _blendElapsed;
        float _holdRemaining;
        string _currentGloss;
        enum State { Idle, Blending, Playing, Holding }
        State _state = State.Idle;

        void Awake()
        {
            if (player == null) player = GetComponent<SignPlayer>();
        }

        public void Clear()
        {
            _queue.Clear();
            _state = State.Idle;
        }

        public void Enqueue(SignClip clip, string gloss)
        {
            _queue.Enqueue((clip, gloss));
            if (_state == State.Idle) Advance();
        }

        void Advance()
        {
            if (_queue.Count == 0)
            {
                _state = State.Idle;
                OnSequenceFinished?.Invoke();
                return;
            }

            var (clip, gloss) = _queue.Dequeue();
            _currentGloss = gloss;

            var previous = player.Clip != null ? player.CapturePose() : null;
            player.Load(clip);
            player.Seek(0f);

            if (previous == null)
            {
                StartPlaying();
                return;
            }

            _blendFrom = previous;
            _blendDuration = TransitionFor(previous, player.CapturePose());
            _blendElapsed = 0f;
            _state = State.Blending;
        }

        /// <summary>Longer cross-fade when the two poses are further apart.</summary>
        float TransitionFor(Quaternion[] a, Quaternion[] b)
        {
            float worst = 0f;
            int n = Mathf.Min(a.Length, b.Length);
            for (int i = 0; i < n; i++)
                worst = Mathf.Max(worst, Quaternion.Angle(a[i], b[i]));

            float t = Mathf.InverseLerp(5f, 90f, worst);
            return Mathf.Lerp(minTransition, maxTransition, t);
        }

        void StartPlaying()
        {
            _state = State.Playing;
            OnSignStarted?.Invoke(_currentGloss);
            player.Play();
        }

        void Update()
        {
            switch (_state)
            {
                case State.Blending:
                    _blendElapsed += Time.deltaTime;
                    float k = _blendDuration > 0f ? Mathf.Clamp01(_blendElapsed / _blendDuration) : 1f;
                    player.ApplyBlended(_blendFrom, 0f, Mathf.SmoothStep(0f, 1f, k));
                    if (k >= 1f) StartPlaying();
                    break;

                case State.Playing:
                    if (!player.IsPlaying)
                    {
                        _holdRemaining = holdSeconds;
                        _state = State.Holding;
                    }
                    break;

                case State.Holding:
                    _holdRemaining -= Time.deltaTime;
                    if (_holdRemaining <= 0f) Advance();
                    break;
            }
        }
    }
}
