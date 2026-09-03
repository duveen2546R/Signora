using System.Runtime.InteropServices;
using Signora.Retargeting;
using UnityEngine;

namespace Signora.Tracking
{
    public static class SignoraRuntimeBootstrap
    {
        private const string RuntimeObjectName = "SignoraTrackingRuntime";
        private const string AvatarObjectName = "SignoraNewAvatar";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Install()
        {
            if (GameObject.Find(RuntimeObjectName) != null) return;
            var avatar = GameObject.Find(AvatarObjectName);
            if (avatar == null)
            {
                Debug.LogError($"Signora: scene does not contain an active GameObject named '{AvatarObjectName}'.");
                return;
            }

            var runtime = new GameObject(RuntimeObjectName);
            var receiver = runtime.AddComponent<WebGLTrackingReceiver>();
            var driver = runtime.AddComponent<SignoraAvatarDriver>();
            driver.Initialize(avatar, receiver.Store);
            receiver.Initialize(driver);
            NotifyBrowserReady();
        }

        private static void NotifyBrowserReady()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            Signora_SetUnityReady();
#else
            Debug.Log("Signora: tracking runtime ready.");
#endif
        }

#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")]
        private static extern void Signora_SetUnityReady();
#endif
    }
}

