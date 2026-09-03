using System;
using UnityEngine;

namespace Signora.Tracking
{
    public static class CanonicalTrackingSchema
    {
        public const int Version = 1;
        public const int PoseLandmarkCount = 33;
        public const int HandLandmarkCount = 21;
    }

    [Serializable]
    public sealed class CanonicalLandmark
    {
        public float x;
        public float y;
        public float z;
        public float confidence;

        public Vector3 Position => new Vector3(x, y, z);
    }

    [Serializable]
    public sealed class CanonicalPose
    {
        public bool present;
        public float confidence;
        public CanonicalLandmark[] landmarks = Array.Empty<CanonicalLandmark>();
    }

    [Serializable]
    public sealed class CanonicalHand
    {
        public bool present;
        public float confidence;
        public string handedness = string.Empty;
        public CanonicalLandmark[] landmarks = Array.Empty<CanonicalLandmark>();
    }

    [Serializable]
    public sealed class CanonicalBlendshape
    {
        public string name = string.Empty;
        public float score;
    }

    [Serializable]
    public sealed class CanonicalFace
    {
        public bool present;
        public float confidence;
        public float[] transform = Array.Empty<float>();
        public CanonicalBlendshape[] blendshapes = Array.Empty<CanonicalBlendshape>();
    }

    [Serializable]
    public sealed class CanonicalTrackingFrameV1
    {
        public int schemaVersion;
        public int sequence;
        public double captureTimeMs;
        public double inferenceEndTimeMs;
        public string source = string.Empty;
        public string state = string.Empty;
        public CanonicalPose pose = new CanonicalPose();
        public CanonicalHand leftHand = new CanonicalHand();
        public CanonicalHand rightHand = new CanonicalHand();
        public CanonicalFace face = new CanonicalFace();

        public bool IsStructurallyValid(out string error)
        {
            if (schemaVersion != CanonicalTrackingSchema.Version)
            {
                error = $"Unsupported tracking schema {schemaVersion}.";
                return false;
            }
            if (pose == null || pose.landmarks == null || pose.landmarks.Length != CanonicalTrackingSchema.PoseLandmarkCount)
            {
                error = "Pose landmark count is invalid.";
                return false;
            }
            if (!HandIsValid(leftHand) || !HandIsValid(rightHand))
            {
                error = "Hand landmark count is invalid.";
                return false;
            }
            if (face == null || face.transform == null || face.transform.Length != 16)
            {
                error = "Face transform is invalid.";
                return false;
            }
            if (inferenceEndTimeMs < captureTimeMs)
            {
                error = "Tracking timestamps are not monotonic.";
                return false;
            }
            error = string.Empty;
            return true;
        }

        private static bool HandIsValid(CanonicalHand hand)
        {
            return hand != null && hand.landmarks != null && hand.landmarks.Length == CanonicalTrackingSchema.HandLandmarkCount;
        }
    }
}

