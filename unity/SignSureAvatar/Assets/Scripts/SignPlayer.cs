// Plays a .signclip onto a Mecanim Humanoid avatar.
//
// Rotations are written straight to the bone Transforms rather than through HumanPoseHandler:
// muscle space clamps to human-plausible ranges, which flattens the extreme handshapes that
// fingerspelling depends on. Writing in LateUpdate keeps us after anything else that poses the rig.

using System.Collections.Generic;
using UnityEngine;

namespace SignSure
{
    [RequireComponent(typeof(Animator))]
    public sealed class SignPlayer : MonoBehaviour
    {
        [Tooltip("Playback rate multiplier. Signers often prefer a little slower than recorded.")]
        [Range(0.25f, 2f)] public float speed = 1f;

        [Tooltip("Apply the recorded hip translation as well as rotation.")]
        public bool applyRootMotion = false;

        public bool IsPlaying { get; private set; }
        public float Time { get; private set; }
        public SignClip Clip { get; private set; }

        Animator _animator;
        Transform[] _bones;
        Quaternion[] _pose;
        Vector3 _rootRest;

        public System.Action<SignClip> OnClipFinished;

        void Awake()
        {
            _animator = GetComponent<Animator>();
            // Nothing else should be posing the rig while we drive it directly.
            _animator.enabled = false;
            _rootRest = transform.localPosition;
        }

        /// <summary>Bind a clip's bone table to this avatar's transforms. Call once per clip.</summary>
        public void Load(SignClip clip)
        {
            Clip = clip;
            _bones = new Transform[clip.BoneCount];
            _pose = new Quaternion[clip.BoneCount];

            var unmapped = new List<string>();
            for (int i = 0; i < clip.BoneCount; i++)
            {
                if (System.Enum.TryParse(clip.BoneNames[i], out HumanBodyBones bone))
                {
                    _bones[i] = _animator.GetBoneTransform(bone);
                    if (_bones[i] == null) unmapped.Add(clip.BoneNames[i]);
                }
                else
                {
                    unmapped.Add(clip.BoneNames[i]);
                }
            }

            if (unmapped.Count > 0)
            {
                Debug.LogWarning($"SignPlayer: {unmapped.Count} bones in the clip are not mapped on " +
                                 $"this avatar and will not move: {string.Join(", ", unmapped)}");
            }

            Time = 0f;
        }

        public void Play() { if (Clip != null) IsPlaying = true; }
        public void Pause() => IsPlaying = false;

        public void Stop()
        {
            IsPlaying = false;
            Time = 0f;
            ApplyPose(0f);
        }

        public void Seek(float seconds)
        {
            if (Clip == null) return;
            Time = Mathf.Clamp(seconds, 0f, Clip.Duration);
            ApplyPose(Time);
        }

        void LateUpdate()
        {
            if (Clip == null) return;

            if (IsPlaying)
            {
                Time += UnityEngine.Time.deltaTime * speed;
                if (Time >= Clip.Duration)
                {
                    Time = Clip.Duration;
                    IsPlaying = false;
                    ApplyPose(Time);
                    OnClipFinished?.Invoke(Clip);
                    return;
                }
            }

            ApplyPose(Time);
        }

        void ApplyPose(float time)
        {
            Clip.Sample(time, _pose, out var root);

            for (int i = 0; i < _bones.Length; i++)
            {
                if (_bones[i] != null) _bones[i].localRotation = _pose[i];
            }

            if (applyRootMotion && Clip.HasRootMotion)
                transform.localPosition = _rootRest + root;
        }

        /// <summary>Current pose, for the sequencer to blend out of when the next sign starts.</summary>
        public Quaternion[] CapturePose()
        {
            var copy = new Quaternion[_bones.Length];
            for (int i = 0; i < _bones.Length; i++)
                copy[i] = _bones[i] != null ? _bones[i].localRotation : Quaternion.identity;
            return copy;
        }

        public void ApplyBlended(Quaternion[] from, float time, float blend)
        {
            Clip.Sample(time, _pose, out _);
            for (int i = 0; i < _bones.Length; i++)
            {
                if (_bones[i] != null)
                    _bones[i].localRotation = Quaternion.Slerp(from[i], _pose[i], blend);
            }
        }
    }
}
