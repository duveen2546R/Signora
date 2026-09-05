using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Signora.Presentation;
using UnityEngine.Rendering;

namespace Signora.EditorTools
{
    /// <summary>
    /// Builds the studio the signing avatar is read against: a cyclorama backdrop, a contact shadow
    /// that grounds the figure, and a three-point rig.
    ///
    /// The choices here are driven by legibility rather than by looks. A viewer reads sign from the
    /// hands and the face, so the backdrop is a mid blue-grey that sits well clear of skin tones,
    /// and it is unlit so that tone never drifts. The avatar's suit is black, which would otherwise
    /// sink into a backdrop that dark, so the rig leans on a strong cool rim light to hold the
    /// shoulder and head silhouette apart from it. Everything is smooth and static - no texture, no
    /// motion, nothing behind the signer that competes for attention.
    ///
    /// The rig is disposable: running this again deletes the previous <c>SignoraStudio</c> object and
    /// rebuilds it, so hand edits inside it do not survive. Nothing outside it is touched apart from
    /// the main camera - framing, lens and clear colour - the ambient light, and the scene's existing
    /// directional light, which is adopted as the key.
    /// </summary>
    public static class SignoraStudioBackdrop
    {
        const string RootName = "SignoraStudio";
        const string ScenePath = "Assets/Scenes/SampleScene.unity";
        const string MaterialFolder = "Assets/Signora/Art/Materials";
        const string BackdropMaterialPath = MaterialFolder + "/StudioBackdrop.mat";
        const string ShadowMaterialPath = MaterialFolder + "/ContactShadow.mat";

        // The cove. Brightest directly behind the signer, falling away at the edges so the frame
        // closes in on the hands, and darkest along the bottom where a floor would be.
        static readonly Color GlowColor = Hex("#6E8A9B");
        static readonly Color EdgeColor = Hex("#2C3D49");
        static readonly Color FloorColor = Hex("#1D2830");

        // The backdrop quad. Sized to cover the frame out to a 2:1 viewport, since the WebGL canvas
        // is laid out by the page and its aspect is not fixed.
        static readonly Vector3 BackdropPosition = new Vector3(0f, 1.6f, -3.2f);
        static readonly Vector3 BackdropScale = new Vector3(10f, 6.5f, 1f);

        // The avatar prefab is sunk so the camera frames head-and-hands rather than the whole body,
        // which puts its feet here rather than on the origin. The floor line and the contact shadow
        // both hang off this, so re-running the builder after moving the avatar keeps them together.
        const float FootHeight = -0.466f;
        const float ChestHeight = 1.1f;

        // The shot. Measured off the imported avatar: hip joint at y 0.471, shoulders 1.145, eye line
        // 1.256, top of the head 1.400. The box runs from the hip line to a hand's width above the
        // head, which is the interpreter framing - the whole signing space, nothing spare.
        static readonly Vector3 FocusPoint = new Vector3(0f, 0.98f, 0f);
        const float FramingWidth = 1.3f;
        const float FramingHeight = 1.12f;

        // Far enough back that the lens does not distort the face the way a wide angle would, which
        // matters here because mouthing and expression are part of the grammar.
        const float CameraDistance = 1.85f;

        static float BackdropBottom => BackdropPosition.y - BackdropScale.y * 0.5f;
        static float ToBackdropV(float worldY) => (worldY - BackdropBottom) / BackdropScale.y;
        static float HorizonV => ToBackdropV(FootHeight);
        static float GlowCenterV => ToBackdropV(ChestHeight);

        [MenuItem("Signora/Build Studio Backdrop")]
        public static void Build()
        {
            var scene = SceneManager_GetActiveOrOpen();
            BuildInActiveScene();
            EditorSceneManager.MarkSceneDirty(scene);
            Debug.Log($"Signora: built '{RootName}' in {scene.name}.");
        }

        /// <summary>Batch-mode entry point: opens the shipping scene, builds, and saves it.</summary>
        public static void BuildAndSave()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            BuildInActiveScene();
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            AssetDatabase.SaveAssets();
            Debug.Log($"Signora: built '{RootName}' and saved {ScenePath}.");
        }

        static UnityEngine.SceneManagement.Scene SceneManager_GetActiveOrOpen()
        {
            var scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
            return scene.IsValid() ? scene : EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        }

        static void BuildInActiveScene()
        {
            var existing = GameObject.Find(RootName);
            if (existing != null) Undo.DestroyObjectImmediate(existing);

            var root = new GameObject(RootName);
            Undo.RegisterCreatedObjectUndo(root, "Build Studio Backdrop");
            root.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);

            BuildBackdrop(root.transform);
            BuildContactShadow(root.transform);
            BuildLighting(root.transform);
            ConfigureCamera();
            ConfigureAmbient();
        }

        static void BuildBackdrop(Transform parent)
        {
            var material = LoadOrCreateMaterial(BackdropMaterialPath, "Signora/StudioBackdrop");
            material.SetColor("_GlowColor", GlowColor);
            material.SetColor("_EdgeColor", EdgeColor);
            material.SetColor("_FloorColor", FloorColor);
            // UV-space tuning, derived from the quad below so the glow lands behind the signer's
            // chest and the floor line lands on the avatar's feet, wherever the quad is moved to.
            material.SetVector("_GlowCenter", new Vector4(0.5f, GlowCenterV, 0f, 0f));
            material.SetFloat("_GlowRadius", 0.08f);
            material.SetFloat("_GlowSoftness", 0.48f);
            material.SetFloat("_GlowStretch", 1.0f);
            material.SetFloat("_Horizon", HorizonV);
            material.SetFloat("_CoveSoftness", 0.22f);
            material.SetFloat("_Dither", 0.006f);
            EditorUtility.SetDirty(material);

            var quad = MakeQuad("Backdrop", parent, material);
            // Turned to face the camera, which looks down -Z from in front of the avatar.
            quad.transform.SetLocalPositionAndRotation(BackdropPosition, Quaternion.Euler(0f, 180f, 0f));
            quad.transform.localScale = BackdropScale;
        }

        static void BuildContactShadow(Transform parent)
        {
            var material = LoadOrCreateMaterial(ShadowMaterialPath, "Signora/SoftShadowBlob");
            material.SetColor("_Color", new Color(0f, 0f, 0f, 0.45f));
            material.SetFloat("_Radius", 0.08f);
            material.SetFloat("_Softness", 0.34f);
            material.SetFloat("_Power", 2.2f);
            EditorUtility.SetDirty(material);

            var quad = MakeQuad("Contact Shadow", parent, material);
            // Laid flat just above the origin, so it does not z-fight anything placed at the feet.
            quad.transform.SetLocalPositionAndRotation(new Vector3(0f, FootHeight + 0.01f, -0.05f), Quaternion.Euler(90f, 0f, 0f));
            quad.transform.localScale = new Vector3(1.5f, 1.5f, 1f);
        }

        static void BuildLighting(Transform parent)
        {
            var rig = new GameObject("Lighting");
            rig.transform.SetParent(parent, false);

            // Adopt the scene's existing directional light as the key rather than adding a fourth
            // one beside it - two keys would double the exposure on the avatar.
            var key = FindExistingDirectionalLight(parent);
            if (key == null) key = new GameObject("Key Light").AddComponent<Light>();
            key.gameObject.name = "Key Light";
            key.transform.SetParent(rig.transform, false);
            key.type = LightType.Directional;
            key.transform.localRotation = Quaternion.Euler(35f, -145f, 0f); // high, front, camera-left
            key.color = Hex("#FFF4E8");
            key.intensity = 1.5f;
            // The stock scene light runs on a 5000 K temperature, which would tint every colour set
            // here. The rig picks its own warm/cool balance, so take the filter off.
            key.useColorTemperature = false;
            key.shadows = LightShadows.Soft;
            key.shadowStrength = 0.6f;

            var fill = MakeLight("Fill Light", rig.transform);
            fill.transform.localRotation = Quaternion.Euler(12f, 145f, 0f); // low, front, camera-right
            fill.color = Hex("#DCE9F2");
            fill.intensity = 0.55f;
            fill.shadows = LightShadows.None;

            // The one light the whole design depends on: a black suit against a mid-dark backdrop
            // has almost no edge of its own, so this draws one.
            var rim = MakeLight("Rim Light", rig.transform);
            rim.transform.localRotation = Quaternion.Euler(28f, 20f, 0f); // behind and above the avatar
            rim.color = Hex("#CFE4F2");
            rim.intensity = 2.0f;
            rim.shadows = LightShadows.None;
        }

        static Light FindExistingDirectionalLight(Transform excludeUnder)
        {
            foreach (var light in Object.FindObjectsByType<Light>(FindObjectsInactive.Include))
            {
                if (light.type != LightType.Directional) continue;
                if (light.transform.IsChildOf(excludeUnder)) continue;
                return light;
            }
            return null;
        }

        static Light MakeLight(string name, Transform parent)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var light = go.AddComponent<Light>();
            light.type = LightType.Directional;
            light.useColorTemperature = false;
            return light;
        }

        static GameObject MakeQuad(string name, Transform parent, Material material)
        {
            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = name;
            Object.DestroyImmediate(quad.GetComponent<MeshCollider>());
            quad.transform.SetParent(parent, false);

            var renderer = quad.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.lightProbeUsage = LightProbeUsage.Off;
            renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
            renderer.motionVectorGenerationMode = MotionVectorGenerationMode.ForceNoMotion;
            return quad;
        }

        static void ConfigureCamera()
        {
            var camera = Camera.main;
            if (camera == null) return;

            // Solid colour rather than the default skybox: the backdrop covers the frame, and this
            // keeps any sliver past its edge matching instead of flashing sky blue.
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = EdgeColor;

            // Square on to the avatar, which faces +Z, and level with the middle of the frame. Level
            // matters: tilting to find the face would splay the vertical of the figure and the
            // backdrop against each other, and the shot should read as a camera on a tripod.
            camera.transform.SetPositionAndRotation(
                new Vector3(FocusPoint.x, FocusPoint.y, FocusPoint.z + CameraDistance),
                Quaternion.Euler(0f, 180f, 0f));

            // Authored for the widest canvas the page produces; the framing component drives the
            // real value from the live aspect at runtime.
            camera.usePhysicalProperties = false;
            camera.fieldOfView = 2f * Mathf.Atan2(FramingHeight * 0.5f, CameraDistance) * Mathf.Rad2Deg;

            var framing = camera.GetComponent<SignoraCameraFraming>();
            if (framing == null) framing = Undo.AddComponent<SignoraCameraFraming>(camera.gameObject);
            var so = new SerializedObject(framing);
            so.FindProperty("focusPoint").vector3Value = FocusPoint;
            so.FindProperty("framingWidth").floatValue = FramingWidth;
            so.FindProperty("framingHeight").floatValue = FramingHeight;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        static void ConfigureAmbient()
        {
            // Flat ambient in the backdrop's own family, so bounce on the avatar agrees with what is
            // behind it. The default skybox ambient reads distinctly blue against this cove.
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = Hex("#35424C");
            RenderSettings.ambientIntensity = 1f;
        }

        static Material LoadOrCreateMaterial(string path, string shaderName)
        {
            var shader = Shader.Find(shaderName);
            if (shader == null) throw new System.InvalidOperationException($"Signora: shader '{shaderName}' not found.");

            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(shader);
                var folder = System.IO.Path.GetDirectoryName(path).Replace('\\', '/');
                if (!AssetDatabase.IsValidFolder(folder)) System.IO.Directory.CreateDirectory(folder);
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != shader)
            {
                material.shader = shader;
            }
            return material;
        }

        static Color Hex(string html)
        {
            ColorUtility.TryParseHtmlString(html, out var color);
            return color;
        }
    }
}
