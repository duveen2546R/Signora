using System;
using System.Collections.Generic;
using Signora.Tracking;
using UnityEngine;

namespace Signora.Retargeting
{
    public sealed class FaceRetargeter
    {
        private readonly Dictionary<string, List<BlendshapeTarget>> _targets = new Dictionary<string, List<BlendshapeTarget>>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, float> _smoothedValues = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);

        public FaceRetargeter(AvatarRig rig)
        {
            foreach (var renderer in rig.Renderers)
            {
                var mesh = renderer.sharedMesh;
                if (mesh == null) continue;
                for (var index = 0; index < mesh.blendShapeCount; index++)
                {
                    var name = mesh.GetBlendShapeName(index);
                    var frameCount = mesh.GetBlendShapeFrameCount(index);
                    if (frameCount == 0) continue;
                    var maximumFrameWeight = Mathf.Abs(mesh.GetBlendShapeFrameWeight(index, frameCount - 1));
                    if (!float.IsFinite(maximumFrameWeight) || maximumFrameWeight <= 0f) continue;
                    if (!_targets.TryGetValue(name, out var targets))
                    {
                        targets = new List<BlendshapeTarget>();
                        _targets.Add(name, targets);
                    }
                    targets.Add(new BlendshapeTarget(renderer, index, maximumFrameWeight));
                }
            }
        }

        public int MappedBlendshapeCount => _targets.Count;

        public void Apply(CanonicalFace face)
        {
            if (face == null || !face.present || face.blendshapes == null) return;
            var interpolation = 1f - Mathf.Exp(-18f * Time.deltaTime);
            foreach (var blendshape in face.blendshapes)
            {
                if (blendshape == null || string.IsNullOrWhiteSpace(blendshape.name) || !_targets.TryGetValue(blendshape.name, out var targets)) continue;
                var normalized = Mathf.Clamp01((blendshape.score - 0.025f) / 0.975f);
                _smoothedValues.TryGetValue(blendshape.name, out var previous);
                var smoothed = Mathf.Lerp(previous, normalized, interpolation);
                _smoothedValues[blendshape.name] = smoothed;
                foreach (var target in targets)
                    target.Renderer.SetBlendShapeWeight(target.Index, ToRendererWeight(smoothed, target.MaximumFrameWeight));
            }
        }

        public void BlendToNeutral(float amount)
        {
            amount = Mathf.Clamp01(amount);
            var names = new List<string>(_smoothedValues.Keys);
            foreach (var name in names)
            {
                var normalized = Mathf.Lerp(_smoothedValues[name], 0f, amount);
                _smoothedValues[name] = normalized;
                if (!_targets.TryGetValue(name, out var targets)) continue;
                foreach (var target in targets)
                    target.Renderer.SetBlendShapeWeight(target.Index, ToRendererWeight(normalized, target.MaximumFrameWeight));
            }
        }

        // Unity blendshape frame weights are importer-defined. Native Unity assets commonly
        // use 100, while this avatar's glTF morph targets use 1. Always scale by the actual
        // final frame weight; assuming 100 extrapolates glTF vertex deltas by 100x.
        public static float ToRendererWeight(float normalizedWeight, float maximumFrameWeight) =>
            Mathf.Clamp01(normalizedWeight) * Mathf.Max(0f, maximumFrameWeight);

        private readonly struct BlendshapeTarget
        {
            public BlendshapeTarget(SkinnedMeshRenderer renderer, int index, float maximumFrameWeight)
            {
                Renderer = renderer;
                Index = index;
                MaximumFrameWeight = maximumFrameWeight;
            }

            public SkinnedMeshRenderer Renderer { get; }
            public int Index { get; }
            public float MaximumFrameWeight { get; }
        }
    }
}
