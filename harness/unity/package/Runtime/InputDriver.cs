using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.Scripting;

namespace Expectrail.Harness
{
    /// <summary>
    /// Presses keys on a virtual keyboard as the route says. Every device the player's machine
    /// reports is removed, so only the harness's devices can drive the game, and focus is ignored,
    /// so a window without focus under Xvfb still takes input.
    /// </summary>
    [Preserve]
    internal sealed class InputDriver
    {
        readonly Dictionary<string, Key> _keys = new Dictionary<string, Key>();
        readonly string[] _deviceNames;
        readonly List<InputDevice> _ours = new List<InputDevice>();
        readonly List<InputDevice> _strays = new List<InputDevice>();
        readonly HashSet<Key> _pressed = new HashSet<Key>();
        Keyboard _keyboard;
        bool _dirty;

        public InputDriver(MapDoc map)
        {
            _deviceNames = map.devices;
            foreach (var a in map.actions)
            {
                if (a.device != "Keyboard")
                    throw new ArgumentException($"action {a.name}: only keyboard actions are supported, not {a.device}");
                _keys[a.name] = (Key)Enum.Parse(typeof(Key), a.key, true);
            }
            if (_keys.Count > 0 && !_deviceNames.Contains("Keyboard"))
                throw new ArgumentException("the map's actions use a keyboard but its devices do not list one");
        }

        public bool Knows(string action) => _keys.ContainsKey(action);

        public void Install()
        {
            InputSystem.settings.backgroundBehavior = InputSettings.BackgroundBehavior.IgnoreFocus;
            foreach (var device in InputSystem.devices.ToArray())
                InputSystem.RemoveDevice(device);
            foreach (var name in _deviceNames)
                _ours.Add(Add(name));
            InputSystem.onDeviceChange += OnDeviceChange;
        }

        InputDevice Add(string name)
        {
            switch (name)
            {
                case "Keyboard": return _keyboard = InputSystem.AddDevice<Keyboard>("ExpectrailKeyboard");
                case "Mouse": return InputSystem.AddDevice<Mouse>("ExpectrailMouse");
                case "Gamepad": return InputSystem.AddDevice<Gamepad>("ExpectrailGamepad");
                case "Touchscreen": return InputSystem.AddDevice<Touchscreen>("ExpectrailTouchscreen");
                default: throw new ArgumentException("unknown device " + name);
            }
        }

        void OnDeviceChange(InputDevice device, InputDeviceChange change)
        {
            // Removed on the next frame, outside the Input System's own callback.
            if (change == InputDeviceChange.Added && !_ours.Contains(device)) _strays.Add(device);
        }

        /// <summary>Remove any device the machine reported since the last frame.</summary>
        public int RemoveStrays()
        {
            var n = 0;
            foreach (var device in _strays)
            {
                if (device.added) { InputSystem.RemoveDevice(device); n++; }
            }
            _strays.Clear();
            return n;
        }

        /// <summary>
        /// Apply one tick's events. The new keyboard state is queued now, before the frame's fixed
        /// update, and the Input System processes it in this frame's input update, before any Update.
        /// </summary>
        public void Apply(List<RouteEvent> events)
        {
            if (events != null)
            {
                foreach (var e in events)
                {
                    var key = _keys[e.action];
                    _dirty |= e.pressed ? _pressed.Add(key) : _pressed.Remove(key);
                }
            }
            if (!_dirty) return;
            InputSystem.QueueStateEvent(_keyboard, new KeyboardState(_pressed.OrderBy(k => (int)k).ToArray()));
            _dirty = false;
        }
    }
}
