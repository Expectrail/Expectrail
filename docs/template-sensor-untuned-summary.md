# Frozen template sensor: untuned measurement record (#262)

This records the preceding local diagnostic measurement, supplied to the #244
audit. The measurement runner is a separate handover, not part of main at the
audit base `522ac07f25a71d1dcf58efc71b46260bf86d991e`. This page adds no sensor,
threshold, template bank or verdict integration. It is not a hosted CI result.

| Clean source / unchanged bank | Previously unseen PNGs with alarms / evaluated | Rate | Scope |
| --- | ---: | ---: | --- |
| Platformer, previously unused coins route | 0 / 97 | 0.00% | 23 of 120 raw frames repeat prior PNG hashes |
| Platformer, new action schedule | 8 / 341 | **2.35%** | 19 of 360 raw frames repeat prior hashes |
| Platformer pooled | 8 / 438 | 1.83% | Does not establish under 2% on each route |
| kinematic-character, original robot bank | 540 / 540 | **100%** | Presence-only cross-art transfer; platformer floor map inapplicable |
| kinematic-character, separate project bank | unavailable | unavailable | Frozen builder refuses fully opaque 16×16 art; no calibrated-bank result |

The under-2% bar across untuned sources is **not demonstrated**. All eight new-route
alarms are presence misses after shooting pulses; their region evidence is also
missing. They are not excluded as inconvenient frames. The original same-frame
tuning result of 0/390 does not establish performance on new frames.

The frozen sensor is PR #522 head `cfb9c9c171d0a433c92732bffb0a39370a83431a`.
Its 408-template bank canonical SHA-256 is
`a40e0e0e49d729eaeb6e58b3686e0102e2573f6407d2f4ddc1a0de1afd515eb8`;
raw SHA-256 `6d646efd35e96306d10ac7e7ab615c2ee63a3d606e95d8a4d441adf7a7d60235`.
The plan was recorded before capture/measurement in local commit `8da75aa`.
New pixels exclude hashes in the earlier 2,190-frame corpus. Outside calibration
and validation used separate routes before evaluation; no evaluation image was
added to a bank. Godot 4.7.2, NumPy 2.3.5, Pillow 13.0.0, Linux software rendering.

Seeded hidden-player/sinking runs discriminate from clean frames on the platformer
(57/97 and 97/97 event frames on coins; 283/355 and 355/355 on the new route).
New-route paired-clean evidence is 261 and 333 frames respectively. Fall-through
has 12 raw crossings per route, but no new matched clean/candidate crossing pairs;
no new-pixel fall-through discrimination claim is made. Outside invisible-player
alarms do not discriminate: its clean frames alarm too. Outside position detection
is unsupported without an applicable bank/reference map.

The full measurement handover includes the frozen plan, routes, observations,
hash exclusions and bookkeeping tests:
[Expectrail #262 untuned handover](https://drive.google.com/file/d/1DfYyXCH1HCj4gy1KQc5I4Q2kZ1kgJbEs/view).
ZIP SHA-256:
`5e7299e94de9c9b21b702db4f5cf3b49f24e252382fccf1cdc3a1cc86e15cd49`.
The raw observation records are in that handover. Its final suite recorded 3,954 tests OK, 45 skipped.
This audit does not claim to have repeated capture or measurement.

The sensor stays opt-in and experimental. It is not eligible to count toward a
verdict. Supporting the outside art requires further development and then new
untuned evaluation frames.
