using System.Collections.Generic;
using Signora.Tracking;
using UnityEngine;

namespace Signora.Retargeting
{
    public sealed class BodyRetargeter
    {
        private static readonly int[] RequiredLandmarks = { 11, 12, 13, 14, 15, 16, 23, 24 };
        private readonly List<DirectionBoneBinding> _armBindings = new List<DirectionBoneBinding>();
        private readonly BasisBoneBinding _torsoBinding;

        public BodyRetargeter(AvatarRig rig)
        {
            AddArm(rig, "LeftArm", 11, 13);
            AddArm(rig, "LeftForeArm", 13, 15);
            AddArm(rig, "RightArm", 12, 14);
            AddArm(rig, "RightForeArm", 14, 16);
            if (rig.TryGetBone("Spine2", out var spine)) _torsoBinding = new BasisBoneBinding(spine, 11, 12, 23);
        }

        public int BindingCount => _armBindings.Count + (_torsoBinding == null ? 0 : 1);
        public int CalibratedBindingCount { get; private set; }

        public bool Calibrate(CanonicalPose pose, float minimumConfidence)
        {
            CalibratedBindingCount = 0;
            if (pose == null || !pose.present || !HasRequiredLandmarks(pose.landmarks, minimumConfidence)) return false;
            var torsoReady = _torsoBinding != null && _torsoBinding.Calibrate(pose.landmarks, minimumConfidence);
            if (torsoReady) CalibratedBindingCount++;
            var armsReady = _armBindings.Count == 4;
            foreach (var binding in _armBindings)
            {
                var ready = binding.Calibrate(pose.landmarks, minimumConfidence);
                armsReady &= ready;
                if (ready) CalibratedBindingCount++;
            }
            return torsoReady && armsReady;
        }

        public void Apply(CanonicalPose pose, float minimumConfidence)
        {
            if (pose == null || !pose.present) return;
            _torsoBinding?.Apply(pose.landmarks, minimumConfidence, 15f, 540f);
            foreach (var binding in _armBindings) binding.Apply(pose.landmarks, minimumConfidence, 18f, 720f);
        }

        public void BlendToBind(float amount)
        {
            _torsoBinding?.BlendToBind(amount);
            foreach (var binding in _armBindings) binding.BlendToBind(amount);
        }

        private void AddArm(AvatarRig rig, string boneName, int from, int to)
        {
            if (rig.TryGetBone(boneName, out var bone)) _armBindings.Add(new DirectionBoneBinding(bone, from, to));
        }

        private static bool HasRequiredLandmarks(CanonicalLandmark[] landmarks, float minimumConfidence)
        {
            foreach (var index in RequiredLandmarks)
            {
                if (!RetargetingMath.TryPoint(landmarks, index, minimumConfidence, out _)) return false;
            }
            return true;
        }
    }
}
