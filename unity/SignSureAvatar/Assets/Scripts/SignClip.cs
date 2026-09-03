// Decoder for the .signclip format produced by backend/app/ingest/clipfmt.py.
// Keep the two in step: the layout is documented in that file's docstring.

using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace SignSure
{
    public sealed class SignClip
    {
        const uint Magic = 0x434E4753;   // "SGNC" little-endian
        const ushort SupportedVersion = 1;
        const int FlagRootMotion = 1 << 0;
        const float Scale = 32767f;

        public float Fps { get; private set; }
        public int FrameCount { get; private set; }
        public string[] BoneNames { get; private set; }
        public ulong RigDigest { get; private set; }
        public bool HasRootMotion { get; private set; }

        // Flat [frame * BoneCount + bone] so playback touches contiguous memory.
        Quaternion[] _rotations;
        Vector3[] _rootPositions;

        public int BoneCount => BoneNames.Length;
        public float Duration => Fps > 0f ? FrameCount / Fps : 0f;

        public static SignClip Parse(byte[] blob)
        {
            if (blob == null || blob.Length < 24)
                throw new InvalidDataException("signclip: blob is shorter than its header.");

            using var reader = new BinaryReader(new MemoryStream(blob), Encoding.UTF8);
            var clip = new SignClip();

            uint magic = reader.ReadUInt32();
            if (magic != Magic)
                throw new InvalidDataException($"signclip: bad magic 0x{magic:X8}.");

            ushort version = reader.ReadUInt16();
            if (version != SupportedVersion)
                throw new InvalidDataException($"signclip: unsupported version {version}.");

            int flags = reader.ReadUInt16();
            clip.Fps = reader.ReadSingle();
            clip.FrameCount = (int)reader.ReadUInt32();
            int boneCount = reader.ReadUInt16();
            clip.RigDigest = reader.ReadUInt64();
            clip.HasRootMotion = (flags & FlagRootMotion) != 0;

            clip.BoneNames = new string[boneCount];
            for (int i = 0; i < boneCount; i++)
            {
                int len = reader.ReadByte();
                clip.BoneNames[i] = Encoding.UTF8.GetString(reader.ReadBytes(len));
            }

            if (clip.HasRootMotion)
            {
                clip._rootPositions = new Vector3[clip.FrameCount];
                for (int f = 0; f < clip.FrameCount; f++)
                {
                    clip._rootPositions[f] = new Vector3(
                        reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                }
            }

            clip._rotations = new Quaternion[clip.FrameCount * boneCount];
            for (int i = 0; i < clip._rotations.Length; i++)
            {
                float x = reader.ReadInt16() / Scale;
                float y = reader.ReadInt16() / Scale;
                float z = reader.ReadInt16() / Scale;
                float w = reader.ReadInt16() / Scale;
                clip._rotations[i] = new Quaternion(x, y, z, w).normalized;
            }

            return clip;
        }

        public Quaternion Rotation(int frame, int bone) => _rotations[frame * BoneCount + bone];

        public Vector3 RootPosition(int frame) =>
            _rootPositions != null ? _rootPositions[frame] : Vector3.zero;

        /// <summary>Pose at an arbitrary time, interpolated between the two bracketing frames.</summary>
        public void Sample(float time, Quaternion[] into, out Vector3 root)
        {
            if (into.Length < BoneCount)
                throw new ArgumentException("destination array is smaller than the bone count.");

            float t = Mathf.Clamp(time * Fps, 0f, FrameCount - 1);
            int a = Mathf.FloorToInt(t);
            int b = Mathf.Min(a + 1, FrameCount - 1);
            float f = t - a;

            for (int i = 0; i < BoneCount; i++)
                into[i] = Quaternion.Slerp(Rotation(a, i), Rotation(b, i), f);

            root = _rootPositions != null
                ? Vector3.Lerp(_rootPositions[a], _rootPositions[b], f)
                : Vector3.zero;
        }
    }
}
