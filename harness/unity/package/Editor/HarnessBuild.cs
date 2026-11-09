using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace Expectrail.Harness.Editor
{
    /// <summary>
    /// Builds the Linux player the harness replays. Called with -executeMethod
    /// Expectrail.Harness.Editor.HarnessBuild.Build on a project copy that harness/unity/run.py
    /// prepared (--prepare-build): it reads expectrail-build.json at the project's root and writes the
    /// player where that file says, relative to the project. Mono, minimal stripping, OpenGL Core,
    /// a 1600 x 960 window, and the EXPECTRAIL_HARNESS define, without which the harness assembly
    /// is not compiled. No scene or script is edited.
    /// </summary>
    public static class HarnessBuild
    {
        public const string Define = "EXPECTRAIL_HARNESS";

        [Serializable]
        class BuildConfig
        {
            public string startScene;
            public string player;
            public int width = 1600;
            public int height = 960;
        }

        public static void Build()
        {
            try
            {
                Run();
            }
            catch (Exception e)
            {
                Debug.LogError("expectrail build: " + e);
                EditorApplication.Exit(1);
            }
        }

        static void Run()
        {
            var project = Directory.GetParent(Application.dataPath).FullName;
            var config = JsonUtility.FromJson<BuildConfig>(File.ReadAllText(Path.Combine(project, "expectrail-build.json")));
            var player = Path.GetFullPath(Path.Combine(project, config.player));

            var enabled = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToList();
            if (!enabled.Contains(config.startScene))
                throw new ArgumentException($"{config.startScene} is not an enabled scene in the build settings");
            // The route starts in this scene, so it is scene 0; the others keep their order.
            var scenes = new[] { config.startScene }.Concat(enabled.Where(s => s != config.startScene)).ToArray();

            var target = NamedBuildTarget.Standalone;
            PlayerSettings.SetScriptingBackend(target, ScriptingImplementation.Mono2x);
            PlayerSettings.SetManagedStrippingLevel(target, ManagedStrippingLevel.Minimal);
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneLinux64, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneLinux64, new[] { GraphicsDeviceType.OpenGLCore });
            PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
            PlayerSettings.defaultScreenWidth = config.width;
            PlayerSettings.defaultScreenHeight = config.height;
            PlayerSettings.resizableWindow = false;
            PlayerSettings.runInBackground = true;
            var defines = PlayerSettings.GetScriptingDefineSymbols(target);
            if (!defines.Split(';').Contains(Define))
                PlayerSettings.SetScriptingDefineSymbols(target, string.IsNullOrEmpty(defines) ? Define : defines + ";" + Define);

            Directory.CreateDirectory(Path.GetDirectoryName(player));
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = player,
                target = BuildTarget.StandaloneLinux64,
                targetGroup = BuildTargetGroup.Standalone,
                options = BuildOptions.None,
                extraScriptingDefines = new[] { Define },
            });
            var summary = report.summary;
            Debug.Log($"expectrail build: {summary.result}, {summary.totalErrors} errors, {summary.totalSize} bytes, " +
                      $"{summary.totalTime.TotalSeconds:F0} s, {player}");
            if (summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException("the player build did not succeed: " + summary.result);

            // Fail closed: a player without the harness assembly would run the game and record nothing.
            var managed = Path.Combine(Path.GetDirectoryName(player), Path.GetFileNameWithoutExtension(player) + "_Data", "Managed");
            if (!File.Exists(Path.Combine(managed, "Expectrail.Harness.dll")))
                throw new InvalidOperationException($"Expectrail.Harness.dll is not in {managed}: the {Define} define did not reach the player build");
        }
    }
}
