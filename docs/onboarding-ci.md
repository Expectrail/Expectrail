# Onboarding review without image extras (#331)

The review page can display the bundled game's small original WebP art without Pillow or NumPy.
It embeds bounded, hash-checked original bytes as `data:image/webp`; the browser decodes the image.
It does not relabel WebP as PNG, fabricate a screenshot, or count a sprite as a measured frame.
The existing PNG-thumbnail path and its 12 KiB limit remain. Original WebP previews have a separate
16 KiB limit and a checked canvas header; the whole page still has its 120 KiB limit.

A missing image decoder previously made `thumbnail()` return `None` for WebP. Both bound objects'
sprites vanished, although the config and page were otherwise produced. The unchanged regression
`tests.test_onboard.ReviewTest.test_download_preserves_every_binding_and_the_game` then failed
`0 != 2` in the local CI-like environment. The new fallback preserves its exact two-image assertion,
all bindings, contained images, no-overwrite behavior, and unchanged project bytes.

## Environments used

A new venv with only the installed package has no runtime dependencies. Onboarding's schema checks
still require the existing contracts extra: the package-only run stops with the explicit instruction
`pip install 'expectrail[contracts]'`. This is separate from the image failure; no image library was
installed to hide it.

For the CI reproduction, the temporary package installation was removed so package-isolation tests
import their own installed wheel. The venv then received exactly the repository's declared test/build
requirements (`requirements-dev.txt`, `requirements-build.txt`), matching CI's install commands.
There is no Pillow or NumPy. The target test reproduces `0 != 2` before the change. Package lists,
full before/after results and the target's green run are in the handover logs. No dependency or
workflow was edited.

The native fallback is only an art preview. If captured frames cannot be decoded/shrunk or are
missing, the page still names their absence and keeps the object's Yes disabled. It does not claim
that the engine's predicted box proves a visible sprite.

## Why the two earlier test changes are intentional

The old page had no interactive answers form, so it could forbid every script. The new page has
one inert `application/json` record and one fixed JavaScript program that downloads answers after
a person supplies a name and decisions. A CSP hash permits exactly that program; `connect-src` and
`form-action` are `none`. The original test still requires exactly two script tags. The new regression
also checks their exact types and code, verifies the hash, rejects extra scripts hidden in payload
text, and forbids network/storage/filesystem APIs. The page never writes an approval or project file.

Previously removing `draft` made a config invalid for the old draft-only page. An active config
without `draft` is now a valid input to the review flow. `draft: false` is still invalid under the
project schema, whose optional `draft` field is `true` when present. The original refusal assertion
keeps that invalid case; a positive CLI regression proves an absent flag is accepted without
changing the project. Neither case approves any spec.

## Approval policy is shared

The existing `expectrail.spec_writer.approve` delegates to `expectrail.approval.approve`.
`onboard --approve FILE` also calls that same writer for each selected spec, after stricter review,
input, name, timing and content-hash checks. It supplies `expected_sha256` as a further race guard;
it never writes an approval itself. The same schema and positional-prompt/object-reference lint run
inside the shared writer. A shared writer refusal propagates through onboarding before a config
or approval is written.

`tests.test_onboard_ci.ApprovalParityTest` exercises positional prompts, unknown objects, invalid
scores/windows/assertions, extra fields and missing instructions. It rebinds forged review hashes
so the test reaches schema/lint enforcement rather than relying on a stale-review rejection. Every
case the old command refuses is also refused by the onboarding CLI, with spec/config bytes unchanged.
A new refusal injected into the shared writer propagates through both commands. All fixtures are
invented temporary specs; no real answers were selected and no committed approval was written.

The three onboarding contracts and their readers/writers are unchanged. Native preview descriptors
are private rendering data, outside the review/answers/timing records; their original project art
remains an input bound by the existing review hashes.
