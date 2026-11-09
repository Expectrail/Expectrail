using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine.Scripting;

namespace Expectrail.Harness
{
    // The route and the per-game map, as JsonUtility reads them (public fields, no dictionaries).

    [Serializable, Preserve]
    public class RouteEvent
    {
        public int tick;
        public string action;
        public bool pressed;
    }

    [Serializable, Preserve]
    public class RouteDoc
    {
        public string format;
        public string name;
        public int ticks;
        public int seed = 1;
        public RouteEvent[] events = new RouteEvent[0];
    }

    [Serializable, Preserve]
    public class MapAction
    {
        public string name;
        public string inputAction;
        public string device;
        public string key;
    }

    [Serializable, Preserve]
    public class MapRole
    {
        public string role;
        public string component;
        public string tag;
    }

    [Serializable, Preserve]
    public class MapPlayer
    {
        public string onFloorCollider;
        public string[] onFloorLayers = new string[0];
    }

    [Serializable, Preserve]
    public class MapGround
    {
        public string[] tilemaps = new string[0];
        public float sinkWindowPx = 64f;
        public float bodyHalfWidthPx = 20f;
        public int searchCells = 16;
    }

    [Serializable, Preserve]
    public class MapFade
    {
        public string component;
        public float restAlpha = -1f;
    }

    [Serializable, Preserve]
    public class MapSettle
    {
        public MapFade[] fades = new MapFade[0];
        public string[] seenThenGone = new string[0];
        public int maxTicks = 500;
        public float maxRealSeconds = 120f;
    }

    [Serializable, Preserve]
    public class MapDoc
    {
        public string format;
        public string scene;
        public float pixelsPerUnit = 100f;
        public int physicsTicksPerSecond;
        public int frameWidth = 1600;
        public int frameHeight = 960;
        public string[] devices = new string[0];
        public MapAction[] actions = new MapAction[0];
        public MapRole[] roles = new MapRole[0];
        public MapPlayer player = new MapPlayer();
        public MapGround ground = new MapGround();
        public MapSettle settle = new MapSettle();
    }

    /// <summary>
    /// A small JSON writer: JsonUtility cannot write nested or mixed arrays. Numbers are rounded and
    /// written with the invariant culture, so two runs that computed the same values write the same
    /// bytes; a value that is not finite is written as null.
    /// </summary>
    internal sealed class JsonText
    {
        readonly StringBuilder _b = new StringBuilder();
        bool _comma;

        public override string ToString() => _b.ToString();

        public JsonText Raw(string json) { Sep(); _b.Append(json); _comma = true; return this; }

        public JsonText Key(string name) { Sep(); Str(name); _b.Append(':'); _comma = false; return this; }

        public JsonText Open(char c) { Sep(); _b.Append(c); _comma = false; return this; }

        public JsonText Close(char c) { _b.Append(c); _comma = true; return this; }

        public JsonText Value(string s) { Sep(); if (s == null) _b.Append("null"); else Str(s); _comma = true; return this; }

        public JsonText Value(bool v) { Sep(); _b.Append(v ? "true" : "false"); _comma = true; return this; }

        public JsonText Value(int v) { Sep(); _b.Append(v.ToString(CultureInfo.InvariantCulture)); _comma = true; return this; }

        public JsonText Value(double v, int decimals) { Sep(); _b.Append(Number(v, decimals)); _comma = true; return this; }

        public JsonText Numbers(IList<double> values, int decimals)
        {
            Open('[');
            foreach (var v in values) Value(v, decimals);
            return Close(']');
        }

        public static string Number(double v, int decimals)
        {
            if (double.IsNaN(v) || double.IsInfinity(v)) return "null";
            // + 0.0 turns a negative zero into zero.
            var r = Math.Round(v, decimals, MidpointRounding.AwayFromZero) + 0.0;
            return r.ToString("0.########", CultureInfo.InvariantCulture);
        }

        void Sep() { if (_comma) _b.Append(','); }

        void Str(string s)
        {
            _b.Append('"');
            foreach (var ch in s)
            {
                switch (ch)
                {
                    case '"': _b.Append("\\\""); break;
                    case '\\': _b.Append("\\\\"); break;
                    case '\n': _b.Append("\\n"); break;
                    case '\r': _b.Append("\\r"); break;
                    case '\t': _b.Append("\\t"); break;
                    default:
                        if (ch < 0x20) _b.Append("\\u").Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                        else _b.Append(ch);
                        break;
                }
            }
            _b.Append('"');
        }
    }
}
