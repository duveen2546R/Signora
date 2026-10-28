using System;
using System.Collections.Generic;
using System.IO;
using Signora.Presentation;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace Signora.Editor
{
    /// <summary>
    /// Restores the authored Avaturn texture maps on the in-scene signer.
    ///
    /// The GLB deliberately remains the single source for the mesh and rig.  Its embedded images
    /// are extracted into Assets/Signora/Art/AvatarTextures so URP can import them normally, then
    /// this tool creates ordinary URP/Lit material assets and assigns them to the scene instance.
    /// No bones, blendshapes, capture motion, or phase timestamps are changed.
    /// </summary>
    public static class SignoraAvatarAppearance
    {
        const string TextureFolder = "Assets/Signora/Art/AvatarTextures";
        const string MaterialFolder = "Assets/Signora/Art/Materials/Avatar";
        const string AvatarName = "SignoraNewAvatar";

        [MenuItem("Signora/Apply Avatar Appearance")]
        public static void Apply()
        {
            var avatar = GameObject.Find(AvatarName);
            if (avatar == null)
                throw new InvalidOperationException($"Signora: no active scene object named '{AvatarName}' was found.");

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null)
                throw new InvalidOperationException("Signora: Universal Render Pipeline/Lit shader was not found.");

            EnsureFolder(MaterialFolder);
            var materials = new Dictionary<string, Material>(StringComparer.OrdinalIgnoreCase)
            {
                ["Body_Mesh"] = Material(shader, "Avatar_Body", "texture_1.jpg", 0f, 0.35f),
                ["Head_Mesh"] = Material(shader, "Avatar_Head", "texture_11.jpg", 0f, 0.35f),
                ["Eye_Mesh"] = Material(shader, "Avatar_Eyes", "texture_4.png", 0f, 0.15f),
                ["EyeAO_Mesh"] = Material(shader, "Avatar_EyeAO", "texture_7.png", 0f, 0.2f, alphaClip: true),
                ["Eyelash_Mesh"] = Material(shader, "Avatar_Eyelashes", "texture_7.png", 0f, 0.15f, alphaClip: true),
                ["Teeth_Mesh"] = Material(shader, "Avatar_Teeth", "texture_14.png", 0f, 0.2f),
                ["Tongue_Mesh"] = Material(shader, "Avatar_Teeth", "texture_14.png", 0f, 0.2f),
                ["avaturn_hair_0"] = Material(shader, "Avatar_Hair", "texture_17.png", 0f, 0.2f, alphaClip: true),
                ["avaturn_hair_1"] = Material(shader, "Avatar_Hair", "texture_17.png", 0f, 0.2f, alphaClip: true),
                ["avaturn_shoes_0"] = Material(shader, "Avatar_Shoes", "texture_20.jpg", 0.05f, 0.35f),
                ["avaturn_look_0"] = Material(shader, "Avatar_Suit", "texture_24.jpg", 0.05f, 0.32f),
            };

            var applied = 0;
            foreach (var renderer in avatar.GetComponentsInChildren<Renderer>(true))
            {
                if (!materials.TryGetValue(renderer.gameObject.name, out var material)) continue;
                Undo.RecordObject(renderer, "Apply Signora avatar material");
                renderer.sharedMaterial = material;
                EditorUtility.SetDirty(renderer);
                applied++;
            }

            if (applied == 0)
                throw new InvalidOperationException("Signora: avatar renderers were found, but none matched the expected Avaturn mesh names.");

            EditorSceneManager.MarkSceneDirty(avatar.scene);
            EditorSceneManager.SaveScene(avatar.scene);
            AssetDatabase.SaveAssets();
            Debug.Log($"Signora: applied textured URP materials to {applied} avatar renderers.");
        }

        static Material Material(Shader shader, string name, string textureFile, float metallic,
            float smoothness, bool alphaClip = false)
        {
            var path = $"{MaterialFolder}/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
            }

            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>($"{TextureFolder}/{textureFile}");
            if (texture == null)
                throw new InvalidOperationException($"Signora: missing avatar texture {TextureFolder}/{textureFile}.");

            material.SetTexture("_BaseMap", texture);
            material.SetColor("_BaseColor", Color.white);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Smoothness", smoothness);
            material.SetFloat("_AlphaClip", alphaClip ? 1f : 0f);
            if (alphaClip) material.SetFloat("_Cutoff", 0.5f);
            material.enableInstancing = true;
            EditorUtility.SetDirty(material);
            return material;
        }

        static void EnsureFolder(string assetPath)
        {
            var absolute = Path.Combine(Directory.GetCurrentDirectory(), assetPath);
            Directory.CreateDirectory(absolute);
            AssetDatabase.Refresh();
        }
    }
}
