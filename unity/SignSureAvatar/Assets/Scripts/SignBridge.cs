// The seam between React and Unity.
//
// React sends small JSON playlists in; Unity fetches the clip binaries itself with UnityWebRequest
// rather than having them pushed through SendMessage, which only carries strings and would mean
// base64-inflating every clip.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Networking;

namespace SignSure
{
    [Serializable] public class PlaylistItem { public string gloss; public string url; }
    [Serializable] public class Playlist { public PlaylistItem[] items; public float speed = 1f; }

    public sealed class SignBridge : MonoBehaviour
    {
        public SignPlayer player;
        public SignSequencer sequencer;

        [Tooltip("Base URL of the FastAPI backend, e.g. http://localhost:8000")]
        public string apiBaseUrl = "http://localhost:8000";

        readonly Dictionary<string, SignClip> _cache = new();

#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] static extern void SignSureEmit(string evt, string payload);
#else
        static void SignSureEmit(string evt, string payload) =>
            Debug.Log($"SignSure event: {evt} {payload}");
#endif

        void Start()
        {
            if (player == null) player = GetComponent<SignPlayer>();
            if (sequencer == null) sequencer = GetComponent<SignSequencer>();

            sequencer.OnSignStarted += gloss => SignSureEmit("signStart", gloss);
            sequencer.OnSequenceFinished += () => SignSureEmit("playbackEnd", "");

            SignSureEmit("ready", Application.unityVersion);
        }

        /// <summary>Called from React: SendMessage("SignBridge", "PlayPlaylist", json).</summary>
        public void PlayPlaylist(string json)
        {
            try
            {
                var playlist = JsonUtility.FromJson<Playlist>(json);
                if (playlist?.items == null || playlist.items.Length == 0)
                {
                    SignSureEmit("error", "playlist was empty");
                    return;
                }
                player.speed = Mathf.Clamp(playlist.speed <= 0f ? 1f : playlist.speed, 0.25f, 2f);
                StopAllCoroutines();
                sequencer.Clear();
                StartCoroutine(LoadAndQueue(playlist));
            }
            catch (Exception e)
            {
                SignSureEmit("error", $"could not read playlist: {e.Message}");
            }
        }

        public void SetSpeed(string value)
        {
            if (float.TryParse(value, out var s)) player.speed = Mathf.Clamp(s, 0.25f, 2f);
        }

        public void Pause() => player.Pause();
        public void Resume() => player.Play();

        IEnumerator LoadAndQueue(Playlist playlist)
        {
            foreach (var item in playlist.items)
            {
                if (_cache.TryGetValue(item.url, out var cached))
                {
                    sequencer.Enqueue(cached, item.gloss);
                    continue;
                }

                var url = item.url.StartsWith("http") ? item.url : apiBaseUrl + item.url;
                using var request = UnityWebRequest.Get(url);
                request.downloadHandler = new DownloadHandlerBuffer();
                yield return request.SendWebRequest();

                if (request.result != UnityWebRequest.Result.Success)
                {
                    SignSureEmit("error", $"could not load {item.gloss}: {request.error}");
                    continue;
                }

                SignClip clip;
                try
                {
                    clip = SignClip.Parse(request.downloadHandler.data);
                }
                catch (Exception e)
                {
                    SignSureEmit("error", $"{item.gloss} is not a readable clip: {e.Message}");
                    continue;
                }

                _cache[item.url] = clip;
                sequencer.Enqueue(clip, item.gloss);
                SignSureEmit("clipLoaded", item.gloss);
            }
        }
    }
}
