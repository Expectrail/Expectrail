using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Scripting;
using UnityEngine.Tilemaps;

namespace Expectrail.Harness
{
    /// <summary>
    /// Builds one trace row per tick (the fields of contracts/trace.schema.json) from the scene as it
    /// stands after LateUpdate. World coordinates are written in world pixels (Unity units times the
    /// map's pixelsPerUnit) with y negated, so y points down as in the Godot traces.
    /// </summary>
    [Preserve]
    internal sealed class Recorder
    {
        readonly MapDoc _map;
        readonly float _ppu;
        readonly Dictionary<string, Type> _types = new Dictionary<string, Type>();
        // Keyed by the object itself: Unity 6.3 marks the int instance ids obsolete, and an id's order
        // means nothing (docs: Migrate from InstanceID to EntityId).
        readonly Dictionary<GameObject, string> _pathIds = new Dictionary<GameObject, string>();
        readonly Dictionary<string, int> _pathUses = new Dictionary<string, int>();
        readonly Dictionary<GameObject, int> _numericIds = new Dictionary<GameObject, int>();
        int _nextNumericId;
        readonly List<Tilemap> _ground = new List<Tilemap>();
        double[] _lastView;
        string _firstLevel;

        public string LevelSurfaces { get; private set; }
        public string LevelArt { get; private set; }
        public bool Facing { get; private set; }
        public bool OnFloor { get; private set; }
        public List<string> GroundPaths { get; } = new List<string>();
        public string LevelChange { get; private set; }

        public Recorder(MapDoc map)
        {
            _map = map;
            _ppu = map.pixelsPerUnit;
            foreach (var role in map.roles) Resolve(role.component);
            foreach (var fade in map.settle.fades) Resolve(fade.component);
            foreach (var name in map.settle.seenThenGone) Resolve(name);
        }

        // Types, by full name, from any loaded assembly (the game's scripts are in Assembly-CSharp).
        Type Resolve(string fullName)
        {
            if (string.IsNullOrEmpty(fullName)) return null;
            if (_types.TryGetValue(fullName, out var t)) return t;
            t = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType(fullName, false)).FirstOrDefault(x => x != null);
            if (t == null) throw new ArgumentException("no type named " + fullName + " in the player");
            return _types[fullName] = t;
        }

        // ---- Objects ---------------------------------------------------------------------------

        /// <summary>The objects of one role, active or not, in a fixed order: by hierarchy path, then by
        /// sibling order, so objects with the same path are seen in the order they sit in the scene.</summary>
        public List<GameObject> Find(MapRole role)
        {
            var type = Resolve(role.component);
            var found = UnityEngine.Object.FindObjectsByType(type, FindObjectsInactive.Include, FindObjectsSortMode.None)
                .OfType<Component>().Select(c => c.gameObject)
                .Where(go => string.IsNullOrEmpty(role.tag) || go.CompareTag(role.tag))
                .Distinct()
                .OrderBy(Path, StringComparer.Ordinal).ThenBy(Siblings, StringComparer.Ordinal)
                .ToList();
            foreach (var go in found) Id(go);
            return found;
        }

        public bool AnyPresent(string componentName)
        {
            return UnityEngine.Object.FindObjectsByType(Resolve(componentName), FindObjectsInactive.Exclude, FindObjectsSortMode.None).Length > 0;
        }

        /// <summary>The alphas of the CanvasGroups of every live object with this component.</summary>
        public IEnumerable<float> Alphas(string componentName)
        {
            foreach (var c in UnityEngine.Object.FindObjectsByType(Resolve(componentName), FindObjectsInactive.Exclude, FindObjectsSortMode.None).OfType<Component>())
            {
                var group = c.GetComponent<CanvasGroup>() ?? c.GetComponentInChildren<CanvasGroup>(true);
                if (group != null) yield return group.alpha;
            }
        }

        static string Path(GameObject go)
        {
            var names = new List<string>();
            for (var t = go.transform; t != null; t = t.parent) names.Add(t.name);
            names.Reverse();
            return string.Join("/", names);
        }

        static string Siblings(GameObject go)
        {
            var indices = new List<string>();
            for (var t = go.transform; t != null; t = t.parent) indices.Add(t.GetSiblingIndex().ToString("D6"));
            indices.Reverse();
            return string.Join("/", indices);
        }

        /// <summary>The object's hierarchy path when first seen; a later object on the same path gets #2, #3 ...</summary>
        string Id(GameObject go)
        {
            if (_pathIds.TryGetValue(go, out var id)) return id;
            var path = Path(go);
            _pathUses.TryGetValue(path, out var uses);
            _pathUses[path] = uses + 1;
            return _pathIds[go] = uses == 0 ? path : path + "#" + (uses + 1);
        }

        int NumericId(GameObject go)
        {
            if (!_numericIds.TryGetValue(go, out var id)) _numericIds[go] = id = _nextNumericId++;
            return id;
        }

        public GameObject Player()
        {
            var role = _map.roles.FirstOrDefault(r => r.role == "player");
            return role == null ? null : Find(role).FirstOrDefault(go => go.activeInHierarchy);
        }

        // ---- Camera ----------------------------------------------------------------------------

        static Camera Cam() => Camera.main;

        // World pixels (y down) to frame pixels (y down).
        Vector2 ToFrame(Camera cam, double x, double y)
        {
            var s = cam.WorldToScreenPoint(new Vector3((float)(x / _ppu), (float)(-y / _ppu), 0f));
            return new Vector2(s.x, Screen.height - s.y);
        }

        double[] View(Camera cam)
        {
            if (cam == null) return null;
            const double step = 1000.0;
            var o = ToFrame(cam, 0, 0);
            var ex = ToFrame(cam, step, 0);
            var ey = ToFrame(cam, 0, step);
            return new[] { (ex.x - o.x) / step, (ex.y - o.y) / step, (ey.x - o.x) / step, (ey.y - o.y) / step, o.x, o.y };
        }

        /// <summary>Call once a frame after LateUpdate, before any row is recorded, so the next row has
        /// the camera of the frame drawn before it (the view convention of the Godot traces).</summary>
        public double[] TakeView()
        {
            var previous = _lastView;
            _lastView = View(Cam());
            return previous ?? _lastView;
        }

        // ---- Level -----------------------------------------------------------------------------

        void FindGround()
        {
            if (_ground.Count > 0 && _ground.All(t => t != null)) return;
            var level = _ground.Count > 0;
            _ground.Clear();
            GroundPaths.Clear();
            foreach (var tm in UnityEngine.Object.FindObjectsByType<Tilemap>(FindObjectsInactive.Exclude, FindObjectsSortMode.None)
                         .Where(t => _map.ground.tilemaps.Contains(t.gameObject.name))
                         .OrderBy(t => Path(t.gameObject), StringComparer.Ordinal))
            {
                _ground.Add(tm);
                GroundPaths.Add(Path(tm.gameObject));
            }
            var now = string.Join(",", GroundPaths);
            if (_firstLevel == null && _ground.Count > 0)
            {
                _firstLevel = now;
                LevelSurfaces = Surfaces();
                LevelArt = Art();
            }
            else if (level && now != _firstLevel && LevelChange == null)
            {
                LevelChange = now;  // the header keeps the first level's surfaces
            }
        }

        double Px(float units) => units * _ppu;

        string Surfaces()
        {
            var j = new JsonText().Open('[');
            foreach (var tm in _ground)
            {
                var composite = tm.GetComponent<CompositeCollider2D>();
                if (composite != null && composite.pathCount > 0)
                {
                    for (var i = 0; i < composite.pathCount; i++)
                    {
                        var points = new Vector2[composite.GetPathPointCount(i)];
                        composite.GetPath(i, points);
                        j.Open('[');
                        foreach (var p in points)
                        {
                            var w = composite.transform.TransformPoint(p);
                            j.Open('[').Value(Px(w.x), 2).Value(-Px(w.y), 2).Close(']');
                        }
                        j.Close(']');
                    }
                    continue;
                }
                // No composite collider: one square per occupied cell.
                foreach (var cell in tm.cellBounds.allPositionsWithin)
                {
                    if (!tm.HasTile(cell)) continue;
                    var a = tm.CellToWorld(cell);
                    var b = tm.CellToWorld(cell + new Vector3Int(1, 1, 0));
                    j.Open('[');
                    foreach (var (x, y) in new[] { (a.x, a.y), (b.x, a.y), (b.x, b.y), (a.x, b.y) })
                        j.Open('[').Value(Px(x), 2).Value(-Px(y), 2).Close(']');
                    j.Close(']');
                }
            }
            return j.Close(']').ToString();
        }

        // Where the ground tiles are drawn: each cell's sprite bounds around its centre (the tile
        // anchor included), as runs per world-pixel column. Not rendered pixels.
        string Art()
        {
            var rects = new List<(int x0, int x1, int top, int bottom)>();
            foreach (var tm in _ground)
            {
                var renderer = tm.GetComponent<TilemapRenderer>();
                if (renderer == null || !renderer.enabled) continue;
                foreach (var cell in tm.cellBounds.allPositionsWithin)
                {
                    if (!tm.HasTile(cell)) continue;
                    var c = tm.GetCellCenterWorld(cell);
                    var sprite = tm.GetSprite(cell);
                    var e = sprite != null
                        ? Vector3.Scale(sprite.bounds.extents, tm.transform.lossyScale)
                        : Vector3.Scale(tm.layoutGrid.cellSize, tm.transform.lossyScale) * 0.5f;
                    rects.Add(((int)Math.Floor(Px(c.x - e.x)), (int)Math.Ceiling(Px(c.x + e.x)),
                               (int)Math.Floor(-Px(c.y + e.y)), (int)Math.Ceiling(-Px(c.y - e.y))));
                }
            }
            if (rects.Count == 0) return null;
            int x0 = rects.Min(r => r.x0), x1 = rects.Max(r => r.x1);
            int y0 = rects.Min(r => r.top), y1 = rects.Max(r => r.bottom);
            var columns = new List<(int top, int bottom)>[x1 - x0];
            for (var i = 0; i < columns.Length; i++) columns[i] = new List<(int, int)>();
            foreach (var r in rects)
                for (var x = r.x0; x < r.x1; x++) columns[x - x0].Add((r.top, r.bottom));
            var j = new JsonText().Open('{')
                .Key("x0").Value(x0).Key("y0").Value(y0).Key("width").Value(x1 - x0).Key("height").Value(y1 - y0)
                .Key("columns").Open('[');
            foreach (var runs in columns)
            {
                j.Open('[');
                var merged = new List<(int top, int bottom)>();
                foreach (var run in runs.OrderBy(r => r.top))
                {
                    if (merged.Count > 0 && run.top <= merged[merged.Count - 1].bottom)
                        merged[merged.Count - 1] = (merged[merged.Count - 1].top, Math.Max(merged[merged.Count - 1].bottom, run.bottom));
                    else merged.Add(run);
                }
                foreach (var m in merged) j.Open('[').Value(m.top).Value(m.bottom).Close(']');
                j.Close(']');
            }
            return j.Close(']').Close('}').ToString();
        }

        // The top of the highest occupied ground cell under the body, at most sinkWindowPx above its
        // origin, read from the tile grid (never from the player's own colliders).
        double? GroundUnder(Vector3 origin)
        {
            var window = _map.ground.sinkWindowPx / _ppu;
            var half = _map.ground.bodyHalfWidthPx / _ppu;
            float? best = null;
            foreach (var dx in new[] { -half, 0f, half })
            {
                foreach (var tm in _ground)
                {
                    var top = TopInColumn(tm, origin.x + dx, origin.y + window);
                    if (top.HasValue && (!best.HasValue || top.Value > best.Value)) best = top;
                }
            }
            return best.HasValue ? -Px(best.Value) : (double?)null;
        }

        float? TopInColumn(Tilemap tm, float x, float maxY)
        {
            var start = tm.WorldToCell(new Vector3(x, maxY, 0f));
            for (var i = 0; i < _map.ground.searchCells; i++)
            {
                var cell = new Vector3Int(start.x, start.y - i, start.z);
                if (!tm.HasTile(cell)) continue;
                var top = tm.CellToWorld(new Vector3Int(cell.x, cell.y + 1, cell.z)).y;
                if (top <= maxY) return top;
            }
            return null;
        }

        // ---- Rows ------------------------------------------------------------------------------

        public string Row(int tick, double[] view)
        {
            FindGround();
            var cam = Cam();
            var planes = cam != null ? GeometryUtility.CalculateFrustumPlanes(cam) : null;
            var j = new JsonText().Open('{').Key("tick").Value(tick).Key("frame").Value(tick);
            var player = Player();
            if (player != null)
            {
                var p = player.transform.position;
                j.Key("player").Open('[').Value(Px(p.x), 3).Value(-Px(p.y), 3).Close(']');
                var feet = string.IsNullOrEmpty(_map.player.onFloorCollider) ? null
                    : player.GetComponent(Resolve(_map.player.onFloorCollider)) as Collider2D;
                if (feet != null)
                {
                    OnFloor = true;
                    j.Key("onFloor").Value(feet.IsTouchingLayers(LayerMask.GetMask(_map.player.onFloorLayers)));
                }
                var sprite = player.GetComponent<SpriteRenderer>() ?? player.GetComponentInChildren<SpriteRenderer>();
                if (sprite != null)
                {
                    Facing = true;
                    var sign = Math.Sign(sprite.transform.lossyScale.x) * (sprite.flipX ? -1 : 1);
                    j.Key("facing").Value(sign < 0 ? -1 : 1);
                }
                var ground = GroundUnder(p);
                if (ground.HasValue) j.Key("ground").Value(ground.Value, 3);
            }
            var byRole = _map.roles.ToDictionary(r => r.role, Find);
            j.Key("coins").Open('[');
            foreach (var go in Live(byRole, "coin"))
            {
                var p = go.transform.position;
                j.Open('[').Value(Px(p.x), 2).Value(-Px(p.y), 2).Close(']');
            }
            j.Close(']');
            foreach (var (key, role) in new[] { ("enemies", "enemy"), ("projectiles", "projectile") })
            {
                j.Key(key).Open('[');
                foreach (var go in Live(byRole, role))
                {
                    var p = go.transform.position;
                    j.Open('[').Value(NumericId(go)).Value(Px(p.x), 2).Value(-Px(p.y), 2).Close(']');
                }
                j.Close(']');
            }
            if (view != null) j.Key("view").Open('[')
                .Value(view[0], 4).Value(view[1], 4).Value(view[2], 4).Value(view[3], 4).Value(view[4], 3).Value(view[5], 3).Close(']');
            j.Key("objects").Open('[');
            foreach (var role in _map.roles)
                foreach (var go in byRole[role.role])
                    Object(j, go, role.role, cam, planes);
            j.Close(']');
            return j.Close('}').ToString();
        }

        static IEnumerable<GameObject> Live(Dictionary<string, List<GameObject>> byRole, string role)
        {
            return byRole.TryGetValue(role, out var list) ? list.Where(go => go.activeInHierarchy) : Enumerable.Empty<GameObject>();
        }

        void Object(JsonText j, GameObject go, string role, Camera cam, Plane[] planes)
        {
            var renderer = go.GetComponent<Renderer>() ?? go.GetComponentInChildren<Renderer>(true);
            j.Open('{').Key("id").Value(Id(go)).Key("role").Value(role).Key("box");
            if (renderer != null && cam != null)
            {
                var b = renderer.bounds;
                var a = ToFrame(cam, Px(b.min.x), -Px(b.min.y));
                var c = ToFrame(cam, Px(b.max.x), -Px(b.max.y));
                j.Open('[').Value(Math.Min(a.x, c.x), 3).Value(Math.Min(a.y, c.y), 3)
                    .Value(Math.Max(a.x, c.x), 3).Value(Math.Max(a.y, c.y), 3).Close(']');
            }
            else j.Value((string)null);
            var active = go.activeInHierarchy;
            var sprite = renderer as SpriteRenderer;
            var visible = active && renderer != null && renderer.enabled && planes != null
                          && (sprite == null || (sprite.sprite != null && sprite.color.a > 0f))
                          && GeometryUtility.TestPlanesAABB(planes, renderer.bounds);
            j.Key("active").Value(active).Key("visible").Value(visible).Close('}');
        }

        public int PhysicsTicksPerSecond() => (int)Math.Round(1.0 / Time.fixedDeltaTime);
    }
}
