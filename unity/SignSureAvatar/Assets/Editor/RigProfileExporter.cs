// Exports the avatar's rest pose so the Python ingest pipeline can retarget onto it.
//
// Run once per avatar: select the avatar in the Hierarchy, then SignSure > Export Rig Profile.
// Re-run and re-ingest whenever the rig changes - clips carry the profile's digest and a mismatch
// is a hard error at load time rather than a silently wrong pose.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace SignSure.EditorTools
{
    public static class RigProfileExporter
    {
        [MenuItem("SignSure/Export Rig Profile")]
        public static void Export()
        {
            var go = Selection.activeGameObject;
            if (go == null || go.GetComponent<Animator>() == null)
            {
                EditorUtility.DisplayDialog("Export Rig Profile",
                    "Select the avatar GameObject (the one with the Animator) first.", "OK");
                return;
            }

            var animator = go.GetComponent<Animator>();
            if (!animator.isHuman)
            {
                EditorUtility.DisplayDialog("Export Rig Profile",
                    "This avatar is not configured as a Mecanim Humanoid. Set Animation Type to " +
                    "Humanoid in the model's import settings and map every finger bone.", "OK");
                return;
            }

            // Put the rig into Unity's canonical neutral pose (all muscles zero) so the export is
            // deterministic no matter how the model happens to be posed in the scene.
            var handler = new HumanPoseHandler(animator.avatar, animator.transform);
            var pose = new HumanPose();
            handler.GetHumanPose(ref pose);
            for (int i = 0; i < pose.muscles.Length; i++) pose.muscles[i] = 0f;
            handler.SetHumanPose(ref pose);

            var transforms = new Dictionary<HumanBodyBones, Transform>();
            foreach (HumanBodyBones bone in Enum.GetValues(typeof(HumanBodyBones)))
            {
                if (bone == HumanBodyBones.LastBone) continue;
                var t = animator.GetBoneTransform(bone);
                if (t != null) transforms[bone] = t;
            }

            var byTransform = new Dictionary<Transform, HumanBodyBones>();
            foreach (var kv in transforms) byTransform[kv.Value] = kv.Key;

            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.AppendFormat("  \"avatarName\": {0},\n", Quote(go.name));
            sb.AppendFormat("  \"unityVersion\": {0},\n", Quote(Application.unityVersion));
            sb.AppendFormat("  \"exportedUtc\": {0},\n", Quote(DateTime.UtcNow.ToString("o")));
            sb.AppendFormat("  \"hipHeight\": {0},\n",
                F(transforms[HumanBodyBones.Hips].position.y - go.transform.position.y));
            sb.Append("  \"bones\": {\n");

            var names = new List<string>();
            foreach (var kv in transforms) names.Add(kv.Key.ToString());
            names.Sort(StringComparer.Ordinal);

            for (int i = 0; i < names.Count; i++)
            {
                var bone = (HumanBodyBones)Enum.Parse(typeof(HumanBodyBones), names[i]);
                var t = transforms[bone];

                // Nearest ancestor that is itself a mapped humanoid bone; null at the root.
                string humanoidParent = null;
                for (var p = t.parent; p != null; p = p.parent)
                {
                    if (byTransform.TryGetValue(p, out var pb)) { humanoidParent = pb.ToString(); break; }
                }

                var parentRot = t.parent != null ? t.parent.rotation : Quaternion.identity;

                sb.AppendFormat("    {0}: {{", Quote(names[i]));
                sb.AppendFormat("\"humanoidParent\": {0}, ",
                    humanoidParent == null ? "null" : Quote(humanoidParent));
                sb.AppendFormat("\"restRotation\": {0}, ", Quat(t.rotation));
                sb.AppendFormat("\"restPosition\": {0}, ", Vec(t.position - go.transform.position));
                sb.AppendFormat("\"restParentRotation\": {0}", Quat(parentRot));
                sb.Append(i < names.Count - 1 ? "},\n" : "}\n");
            }

            sb.Append("  }\n}\n");

            var path = EditorUtility.SaveFilePanel(
                "Export Rig Profile", Application.dataPath, "rig_profile.json", "json");
            if (string.IsNullOrEmpty(path)) return;

            File.WriteAllText(path, sb.ToString());
            Debug.Log($"SignSure: wrote rig profile for '{go.name}' " +
                      $"({transforms.Count} humanoid bones) to {path}");

            var missing = MissingFingerBones(transforms);
            if (missing.Count > 0)
            {
                Debug.LogWarning("SignSure: this avatar has unmapped finger bones, so those signs " +
                                 "will not read correctly: " + string.Join(", ", missing));
            }
        }

        static List<string> MissingFingerBones(Dictionary<HumanBodyBones, Transform> found)
        {
            var missing = new List<string>();
            string[] sides = { "Left", "Right" };
            string[] fingers = { "Thumb", "Index", "Middle", "Ring", "Little" };
            string[] parts = { "Proximal", "Intermediate", "Distal" };
            foreach (var s in sides)
                foreach (var f in fingers)
                    foreach (var p in parts)
                    {
                        var name = s + f + p;
                        var bone = (HumanBodyBones)Enum.Parse(typeof(HumanBodyBones), name);
                        if (!found.ContainsKey(bone)) missing.Add(name);
                    }
            return missing;
        }

        static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);
        static string Quote(string s) => "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        static string Vec(Vector3 v) => $"[{F(v.x)}, {F(v.y)}, {F(v.z)}]";
        static string Quat(Quaternion q) => $"[{F(q.x)}, {F(q.y)}, {F(q.z)}, {F(q.w)}]";
    }
}
