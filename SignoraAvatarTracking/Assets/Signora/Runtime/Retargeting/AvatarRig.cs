using System.Collections.Generic;
using UnityEngine;

namespace Signora.Retargeting
{
    public sealed class AvatarRig
    {
        private readonly Dictionary<string, Transform> _bones = new Dictionary<string, Transform>();
        private readonly Dictionary<Transform, Quaternion> _bindLocalRotations = new Dictionary<Transform, Quaternion>();

        public AvatarRig(GameObject root)
        {
            Root = root;
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                if (!_bones.ContainsKey(transform.name)) _bones.Add(transform.name, transform);
                _bindLocalRotations[transform] = transform.localRotation;
            }
            Renderers = root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        }

        public GameObject Root { get; }
        public SkinnedMeshRenderer[] Renderers { get; }

        public bool TryGetBone(string name, out Transform transform)
        {
            return _bones.TryGetValue(name, out transform);
        }

        public Quaternion GetBindLocalRotation(Transform bone)
        {
            return _bindLocalRotations.TryGetValue(bone, out var rotation) ? rotation : bone.localRotation;
        }

        public void BlendToBindPose(float amount)
        {
            amount = Mathf.Clamp01(amount);
            foreach (var pair in _bindLocalRotations)
            {
                pair.Key.localRotation = Quaternion.Slerp(pair.Key.localRotation, pair.Value, amount);
            }
        }
    }
}

