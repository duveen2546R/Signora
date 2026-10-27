using System.Collections.Generic;
using Signora.Tracking;

namespace Signora.Retargeting
{
    public sealed class HandRetargeter
    {
        private readonly List<DirectionBoneBinding> _fingerBindings = new List<DirectionBoneBinding>();
        private readonly BasisBoneBinding _palmBinding;

        public HandRetargeter(AvatarRig rig, string side)
        {
            if (rig.TryGetBone($"{side}Hand", out var hand)) _palmBinding = new BasisBoneBinding(hand, 0, 5, 17);

            AddFinger(rig, side, "Thumb", new[] { 1, 2, 3, 4 });
            AddFinger(rig, side, "Index", new[] { 5, 6, 7, 8 });
            AddFinger(rig, side, "Middle", new[] { 9, 10, 11, 12 });
            AddFinger(rig, side, "Ring", new[] { 13, 14, 15, 16 });
            AddFinger(rig, side, "Pinky", new[] { 17, 18, 19, 20 });
        }

        public int BindingCount => _fingerBindings.Count + (_palmBinding == null ? 0 : 1);
        public int CalibratedBindingCount { get; private set; }

        public bool Calibrate(CanonicalHand hand, float minimumConfidence)
        {
            CalibratedBindingCount = 0;
            if (hand == null || !hand.present) return false;
            var palmReady = _palmBinding != null && _palmBinding.Calibrate(hand.landmarks, minimumConfidence);
            if (palmReady) CalibratedBindingCount++;
            var fingersReady = _fingerBindings.Count == 15;
            foreach (var binding in _fingerBindings)
            {
                var ready = binding.Calibrate(hand.landmarks, minimumConfidence);
                fingersReady &= ready;
                if (ready) CalibratedBindingCount++;
            }
            return palmReady && fingersReady;
        }

        public void Apply(CanonicalHand hand, float minimumConfidence)
        {
            if (hand == null || !hand.present || hand.confidence < minimumConfidence) return;
            _palmBinding?.Apply(hand.landmarks, minimumConfidence, 22f, 900f);
            foreach (var binding in _fingerBindings) binding.Apply(hand.landmarks, minimumConfidence, 24f, 1080f);
        }

        public void BlendToBind(float amount)
        {
            _palmBinding?.BlendToBind(amount);
            foreach (var binding in _fingerBindings) binding.BlendToBind(amount);
        }

        private void AddFinger(AvatarRig rig, string side, string finger, int[] landmarks)
        {
            for (var segment = 0; segment < 3; segment++)
            {
                if (rig.TryGetBone($"{side}Hand{finger}{segment + 1}", out var bone))
                {
                    _fingerBindings.Add(new DirectionBoneBinding(bone, landmarks[segment], landmarks[segment + 1]));
                }
            }
        }
    }
}
