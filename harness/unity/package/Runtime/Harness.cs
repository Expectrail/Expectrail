using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.LowLevel;
using UnityEngine.SceneManagement;
using UnityEngine.Scripting;

namespace Expectrail.Harness
{
    /// <summary>
    /// Expectrail's Unity harness. harness/unity/run.py starts a player built with this package and
    /// passes -expectrail-route, -expectrail-map and -expectrail-out; without -expectrail-route the
    /// harness does nothing. It locks one rendered frame to one physics tick, presses keys on the
    /// route's ticks, records one trace row after LateUpdate on every tick, writes a PNG of every
    /// frame, and quits after exactly the route's ticks.
    /// </summary>
    [Preserve]
    public static class Bootstrap
    {
        internal static Run Current;

        [Preserve]
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void OnSubsystemRegistration()
        {
            var args = Args.Parse(Environment.GetCommandLineArgs());
            if (args.Route == null) return;
            Current = new Run(args);
            Current.Guard("start", Current.Start);
        }

        [Preserve]
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void OnBeforeSceneLoad()
        {
            Current?.Guard("before the first scene", Current.BeforeSceneLoad);
        }
    }

    internal sealed class Args
    {
        public string Route, Map, Out;
        public int? Seed;
        public bool Frames = true;

        public static Args Parse(string[] argv)
        {
            var a = new Args();
            for (var i = 0; i < argv.Length; i++)
            {
                string Next() => i + 1 < argv.Length ? argv[++i] : throw new ArgumentException(argv[i] + " needs a value");
                switch (argv[i])
                {
                    case "-expectrail-route": a.Route = Next(); break;
                    case "-expectrail-map": a.Map = Next(); break;
                    case "-expectrail-out": a.Out = Next(); break;
                    case "-expectrail-seed": a.Seed = int.Parse(Next(), System.Globalization.CultureInfo.InvariantCulture); break;
                    case "-expectrail-no-frames": a.Frames = false; break;
                }
            }
            return a;
        }
    }

    // Markers for the systems the harness adds to the player loop.
    internal struct ExpectrailInput { }
    internal struct ExpectrailStep { }
    internal struct ExpectrailRecord { }

    [Preserve]
    internal sealed class Run
    {
        enum Phase { Settle, Route, Done }

        readonly Args _args;
        RouteDoc _route;
        MapDoc _map;
        int _seed;
        readonly Dictionary<int, List<RouteEvent>> _events = new Dictionary<int, List<RouteEvent>>();
        InputDriver _input;
        Recorder _recorder;
        Phase _phase = Phase.Settle;

        int _tick;
        int _stepsThisFrame;
        bool _rowThisFrame;
        readonly List<int> _steps = new List<int>();
        readonly List<string> _rows = new List<string>();
        int _firstFrameCount = -1, _lastFrameCount = -1;
        double _firstFixedTime, _lastFixedTime;

        int _settleFrames, _settleTicks, _frozenFrames;
        // During the route: frames held while a real-time fade was part-way (no tick, row or frame).
        bool _holding;
        int _routeHeldFrames;
        readonly HashSet<string> _seen = new HashSet<string>();
        readonly List<string> _hazards = new List<string>();
        readonly HashSet<string> _hazardKeys = new HashSet<string>();

        int _exceptions, _errors;
        readonly List<string> _messages = new List<string>();

        public Run(Args args) { _args = args; }

        string FramesDir => Path.Combine(_args.Out, "frames");

        public void Guard(string where, Action action)
        {
            if (_phase == Phase.Done) return;
            try { action(); }
            catch (Exception e) { Fail(where, e); }
        }

        // SubsystemRegistration: before anything of the game runs.
        public void Start()
        {
            if (_args.Map == null || _args.Out == null) throw new ArgumentException("-expectrail-map and -expectrail-out are required");
            Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            Application.logMessageReceived += OnLog;
            _route = JsonUtility.FromJson<RouteDoc>(File.ReadAllText(_args.Route));
            _map = JsonUtility.FromJson<MapDoc>(File.ReadAllText(_args.Map));
            if (_route.format != "expectrail.route/v0") throw new ArgumentException("not an expectrail.route/v0 route: " + _route.format);
            if (_route.ticks <= 0) throw new ArgumentException("the route has no ticks");
            _input = new InputDriver(_map);
            foreach (var e in _route.events ?? new RouteEvent[0])
            {
                if (!_input.Knows(e.action)) throw new ArgumentException("the map has no action named " + e.action);
                if (!_events.TryGetValue(e.tick, out var list)) _events[e.tick] = list = new List<RouteEvent>();
                list.Add(e);
            }
            _seed = _args.Seed ?? _route.seed;

            // One rendered frame is one physics tick: the same float for both, so accumulated time
            // never gives a frame zero or two steps.
            Time.captureDeltaTime = Time.fixedDeltaTime;
            QualitySettings.vSyncCount = 0;
            Application.runInBackground = true;
            UnityEngine.Random.InitState(_seed);

            var loop = PlayerLoop.GetCurrentPlayerLoop();
            Append(ref loop, typeof(UnityEngine.PlayerLoop.EarlyUpdate), typeof(ExpectrailInput), () => Guard("input", BeginFrame));
            Append(ref loop, typeof(UnityEngine.PlayerLoop.FixedUpdate), typeof(ExpectrailStep), () => _stepsThisFrame++);
            Append(ref loop, typeof(UnityEngine.PlayerLoop.PreLateUpdate), typeof(ExpectrailRecord), () => Guard("record", Record));
            PlayerLoop.SetPlayerLoop(loop);
            Directory.CreateDirectory(FramesDir);
            Debug.Log($"expectrail: route {_route.name}, {_route.ticks} ticks, seed {_seed}, fixedDeltaTime {Time.fixedDeltaTime}");
        }

        static void Append(ref PlayerLoopSystem root, Type phase, Type marker, PlayerLoopSystem.UpdateFunction fn)
        {
            for (var i = 0; i < root.subSystemList.Length; i++)
            {
                if (root.subSystemList[i].type != phase) continue;
                var list = new List<PlayerLoopSystem>(root.subSystemList[i].subSystemList ?? new PlayerLoopSystem[0])
                {
                    new PlayerLoopSystem { type = marker, updateDelegate = fn }
                };
                root.subSystemList[i].subSystemList = list.ToArray();
                return;
            }
            throw new InvalidOperationException("the player loop has no " + phase.Name + " phase");
        }

        // BeforeSceneLoad: the Input System is up, no scene object has woken.
        public void BeforeSceneLoad()
        {
            UnityEngine.Random.InitState(_seed);
            _recorder = new Recorder(_map);
            _input.Install();
            SceneManager.sceneLoaded += (scene, mode) => Guard("scene load", () => OnSceneLoaded(scene));
            var host = new GameObject("ExpectrailHarness");
            UnityEngine.Object.DontDestroyOnLoad(host);
            host.AddComponent<HarnessHost>().Begin(this);
        }

        void OnSceneLoaded(Scene scene)
        {
            foreach (var animator in UnityEngine.Object.FindObjectsByType<Animator>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (animator.updateMode == AnimatorUpdateMode.UnscaledTime)
                    Hazard("animator-unscaled-time", $"{animator.name} in {scene.name} animates on unscaled (real) time", null);
            }
            foreach (var ps in UnityEngine.Object.FindObjectsByType<ParticleSystem>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (ps.main.useUnscaledTime)
                    Hazard("particles-unscaled-time", $"{ps.name} in {scene.name} simulates on unscaled (real) time", null);
                if (!ps.useAutoRandomSeed) continue;
                // randomSeed can be set only on a stopped system.
                var playing = ps.isPlaying;
                ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                ps.useAutoRandomSeed = false;
                ps.randomSeed = (uint)_seed;
                if (playing) ps.Play(true);
            }
            foreach (var fade in _map.settle.fades)
                Hazard("real-time-fade", $"{fade.component} fades on Time.unscaledDeltaTime; before tick 0 the harness holds game time while it fades", null);
        }

        // Each hazard once: the first tick it was seen on (dedupe on kind and what it is about).
        void Hazard(string kind, string detail, int? tick, string about = null)
        {
            if (!_hazardKeys.Add(kind + "\n" + (about ?? detail))) return;
            var j = new JsonText().Open('{').Key("kind").Value(kind).Key("detail").Value(detail).Key("tick");
            if (tick.HasValue) j.Value(tick.Value); else j.Value((string)null);
            _hazards.Add(j.Close('}').ToString());
        }

        void OnLog(string condition, string stackTrace, LogType type)
        {
            if (type == LogType.Exception) _exceptions++;
            else if (type == LogType.Error || type == LogType.Assert) _errors++;
            else return;
            if (_messages.Count >= 50) return;
            var message = condition.Length > 300 ? condition.Substring(0, 300) : condition;
            _messages.Add(new JsonText().Open('{').Key("type").Value(type.ToString()).Key("message").Value(message).Close('}').ToString());
        }

        // EarlyUpdate: before this frame's fixed update and its input update.
        void BeginFrame()
        {
            // Unity run 7 (42713673108): the player ran 2 and 6 physics steps in a frame, so the lock set in
            // Start did not hold. Set it again every frame; it applies from the next frame's time update.
            if (Time.captureDeltaTime != Time.fixedDeltaTime) Time.captureDeltaTime = Time.fixedDeltaTime;
            _stepsThisFrame = 0;
            _rowThisFrame = false;
            _input.RemoveStrays();
            if (_phase != Phase.Route || _holding) return;
            _events.TryGetValue(_tick, out var events);
            _input.Apply(events);
        }

        bool Fading() => _map.settle.fades.Any(f => _recorder.Alphas(f.component).Any(a => a > 0f && a < 1f));

        // After LateUpdate: every script has moved and the camera is where this frame draws it.
        void Record()
        {
            if (_phase == Phase.Done) return;
            var view = _recorder.TakeView();
            if (_phase != Phase.Route) return;
            // Unity run 10 (42726139650): one player build, two runners, and the route diverged from the
            // death at tick ~113: Fader.cs fades on Time.unscaledDeltaTime, so the level reloaded after a
            // number of ticks that depended on the machine's speed. As before tick 0, hold game time while
            // a real-time fade is part-way: held frames run no physics and give no tick, row or frame.
            var fading = Fading();
            if (_holding)
            {
                _routeHeldFrames++;
                if (_stepsThisFrame != 0)
                    throw new InvalidOperationException($"{_stepsThisFrame} physics steps ran in a frame held for a fade after tick {_tick - 1}: a tick with no row");
                if (!fading) { _holding = false; Time.timeScale = 1f; }
                if (_routeHeldFrames > _map.settle.maxTicks * 10)
                    throw new TimeoutException($"a fade during the route did not come to rest in {_routeHeldFrames} held frames");
                return;
            }
            _steps.Add(_stepsThisFrame);
            if (_stepsThisFrame != 1)
                Debug.LogWarning($"expectrail: tick {_tick} (frame {Time.frameCount}) ran {_stepsThisFrame} physics steps; " +
                    $"deltaTime {Time.deltaTime}, captureDeltaTime {Time.captureDeltaTime}, fixedDeltaTime {Time.fixedDeltaTime}, " +
                    $"timeScale {Time.timeScale}, maximumDeltaTime {Time.maximumDeltaTime}");
            _rows.Add(_recorder.Row(_tick, view));
            if (_firstFrameCount < 0) { _firstFrameCount = Time.frameCount; _firstFixedTime = Time.fixedTimeAsDouble; }
            _lastFrameCount = Time.frameCount;
            _lastFixedTime = Time.fixedTimeAsDouble;
            foreach (var fade in _map.settle.fades)
            {
                if (_recorder.Alphas(fade.component).Any(a => a > 0f && a < 1f))
                    Hazard("real-time-fade-during-route", $"{fade.component} began a real-time fade at tick {_tick}; game time is held until it rests, and only this tick's frame can differ between runs", _tick, fade.component + "@" + _tick);
            }
            if (fading) { _holding = true; Time.timeScale = 0f; }
            if (_recorder.LevelChange != null)
                Hazard("level-changed", "the level was replaced during the route (" + _recorder.LevelChange + "); levelSurfaces describe the first level", _tick, "level");
            Debug.Log($"expectrail: tick {_tick} frameCount {Time.frameCount} fixedTime {Time.fixedTimeAsDouble:F4} steps {_stepsThisFrame}");
            _rowThisFrame = true;
        }

        // After the frame is drawn (HarnessHost's WaitForEndOfFrame).
        public void EndOfFrame()
        {
            if (_phase == Phase.Route && _rowThisFrame)
            {
                if (_args.Frames) Capture(_tick);
                _tick++;
                if (_tick >= _route.ticks) Finish();
                return;
            }
            if (_phase == Phase.Settle) Settle();
        }

        void Capture(int tick)
        {
            var texture = ScreenCapture.CaptureScreenshotAsTexture();
            try { File.WriteAllBytes(Path.Combine(FramesDir, $"f{tick:D8}.png"), texture.EncodeToPNG()); }
            finally { UnityEngine.Object.Destroy(texture); }
        }

        // Before tick 0: wait until the player is there, every seen-then-gone object (the level banner)
        // has come and gone, and every fade is at rest. While a fade that runs on real time is
        // part-way, hold game time (timeScale 0) so the fade takes no ticks.
        void Settle()
        {
            _settleFrames++;
            _settleTicks += _stepsThisFrame;
            var fading = _map.settle.fades.Any(f => _recorder.Alphas(f.component).Any(a => a > 0f && a < 1f));
            var resting = _map.settle.fades.Where(f => f.restAlpha >= 0f)
                .All(f => _recorder.Alphas(f.component).All(a => Mathf.Approximately(a, f.restAlpha)));
            var waiting = false;
            foreach (var name in _map.settle.seenThenGone)
            {
                if (_recorder.AnyPresent(name)) { _seen.Add(name); waiting = true; }
                else if (!_seen.Contains(name)) waiting = true;
            }
            if (fading) _frozenFrames++;
            Time.timeScale = fading ? 0f : 1f;
            if (!fading && resting && !waiting && _recorder.Player() != null)
            {
                _phase = Phase.Route;
                Debug.Log($"expectrail: settled after {_settleTicks} ticks and {_frozenFrames} held frames ({_settleFrames} frames)");
                return;
            }
            if (_settleTicks > _map.settle.maxTicks || Time.realtimeSinceStartup > _map.settle.maxRealSeconds)
                throw new TimeoutException($"the game did not settle: {_settleTicks} ticks, {_frozenFrames} held frames, " +
                                           $"{Time.realtimeSinceStartup:F0} s (fading {fading}, resting {resting}, waiting {waiting})");
        }

        void Finish()
        {
            _phase = Phase.Done;
            var trace = new JsonText().Open('{')
                .Key("format").Value("expectrail.trace/v0")
                .Key("ticks").Value(_route.ticks)
                .Key("physicsTicksPerSecond").Value(_recorder.PhysicsTicksPerSecond())
                .Key("capabilities").Open('{')
                    .Key("enemies").Value(_map.roles.Any(r => r.role == "enemy") ? "complete" : "absent")
                    .Key("projectiles").Value(_map.roles.Any(r => r.role == "projectile") ? "complete" : "absent")
                    .Key("facing").Value(_recorder.Facing)
                    .Key("onFloor").Value(_recorder.OnFloor)
                .Close('}');
            if (_recorder.LevelSurfaces != null) trace.Key("levelSurfaces").Raw(_recorder.LevelSurfaces);
            if (_recorder.LevelArt != null) trace.Key("levelArt").Raw(_recorder.LevelArt);
            trace.Key("rows").Raw("[" + string.Join(",", _rows) + "]").Close('}');
            File.WriteAllText(Path.Combine(_args.Out, "trace.json"), trace.ToString());
            WriteRun("ok", null);
            Debug.Log($"expectrail: wrote {_rows.Count} rows; held {_routeHeldFrames} frames during the route for real-time fades");
            Application.Quit(0);
        }

        void WriteRun(string status, string error)
        {
            var j = new JsonText().Open('{')
                .Key("format").Value("expectrail.unity-run/v0")
                .Key("status").Value(status)
                .Key("error").Value(error)
                .Key("unityVersion").Value(Application.unityVersion)
                .Key("graphics").Open('{')
                    .Key("type").Value(SystemInfo.graphicsDeviceType.ToString())
                    .Key("name").Value(SystemInfo.graphicsDeviceName)
                    .Key("version").Value(SystemInfo.graphicsDeviceVersion)
                .Close('}')
                .Key("screen").Open('[').Value(Screen.width).Value(Screen.height).Close(']')
                .Key("seed").Value(_seed)
                .Key("ticks").Value(_route?.ticks ?? 0)
                .Key("steps").Open('[');
            foreach (var s in _steps) j.Value(s);
            j.Close(']')
                .Key("frameCount").Open('[').Value(_firstFrameCount).Value(_lastFrameCount).Close(']')
                .Key("fixedTime").Open('[').Value(_firstFixedTime, 4).Value(_lastFixedTime, 4).Close(']')
                .Key("settle").Open('{').Key("ticks").Value(_settleTicks).Key("frozenFrames").Value(_frozenFrames).Close('}')
                .Key("groundTilemaps").Open('[');
            foreach (var p in _recorder?.GroundPaths ?? new List<string>()) j.Value(p);
            j.Close(']').Key("hazards").Raw("[" + string.Join(",", _hazards) + "]")
                .Key("integrity").Open('{')
                    .Key("exceptions").Value(_exceptions)
                    .Key("errors").Value(_errors)
                    .Key("messages").Raw("[" + string.Join(",", _messages) + "]")
                .Close('}')
                .Close('}');
            File.WriteAllText(Path.Combine(_args.Out, "run.json"), j.ToString());
        }

        public void Fail(string where, Exception e)
        {
            if (_phase == Phase.Done) return;
            _phase = Phase.Done;
            Debug.LogError($"expectrail: failed at {where}: {e}");
            try
            {
                if (_args.Out != null)
                {
                    Directory.CreateDirectory(_args.Out);
                    WriteRun("error", $"{where}: {e.GetType().Name}: {e.Message}");
                }
            }
            catch (Exception inner) { Debug.LogError("expectrail: could not write run.json: " + inner); }
            Application.Quit(3);
        }
    }
}
