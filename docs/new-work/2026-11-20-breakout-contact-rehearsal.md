# Reproduce a paddle hit and a right-wall rebound on public Breakout (#716)

## What changed

A second pointer route exercises two contacts the registered sweep misses. The public run record identifies each first different Ball frame by path and hash and gives its engine measurement, collider geometry and the direction on the next tick. Three opt-in patches exercise a paddle collision-layer error, a disabled wall and a frozen Ball.

## What was run

Godot 4.7.2 rendered the public route and its controls using a separate Xvfb display per capture. The [rehearsal](../outside-trials/breakout-pointer/contact-rehearsal/README.md) gives the commands and findings.

## Not done

The contacts need fail-closed coverage before a check can judge a candidate. The examples are diagnostic, with local Bubblewrap unavailable. No human approval, independent vision judgement or unaided developer session was run.

## Files

- `docs/outside-trials/breakout-pointer/contact-rehearsal/` contains the route, four frame hashes and the measurements.
- `docs/outside-trials/breakout-pointer/contact-rehearsal/changes/` contains three public game patches used by the rehearsal.
