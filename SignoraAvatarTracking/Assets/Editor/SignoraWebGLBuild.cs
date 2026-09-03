using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;

namespace Signora.Editor
{
    public static class SignoraWebGLBuild
    {
        [MenuItem("Signora/Build WebGL")]
        public static void Build()
        {
            var scenes = EditorBuildSettings.scenes.Where(scene => scene.enabled).Select(scene => scene.path).ToArray();
            if (scenes.Length == 0) throw new InvalidOperationException("No enabled Unity scenes are configured.");

            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = "WebBuild",
                target = BuildTarget.WebGL,
                options = BuildOptions.None
            });
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException($"WebGL build failed with {report.summary.totalErrors} errors.");
        }
    }
}
