using System.Collections;
using UnityEngine;
using UnityEngine.Scripting;

namespace Expectrail.Harness
{
    // In its own file, named for the class, so the player has a script for it (AddComponent).
    /// <summary>Holds the end-of-frame coroutine; lives for the whole run.</summary>
    [Preserve]
    public sealed class HarnessHost : MonoBehaviour
    {
        Run _run;

        internal void Begin(Run run)
        {
            _run = run;
            StartCoroutine(EndOfFrames());
        }

        IEnumerator EndOfFrames()
        {
            var wait = new WaitForEndOfFrame();
            while (true)
            {
                yield return wait;
                _run.Guard("end of frame", _run.EndOfFrame);
            }
        }
    }
}
