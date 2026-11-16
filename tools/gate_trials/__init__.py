"""Local preparation and unauthenticated, read-only observation of hosted trials."""

KINDS = ('correct-fix', 'wrong-fix', 'new-head', 'tamper', 'fork', 'branch-enforcement')
EVIDENCE = 'Expectrail evidence'
CLEARANCE = 'Expectrail clearance'
APP_ID = 5755185
APP_SLUG = 'expectrail-checks'
SPEC = 'player-stays-above-ground'
MARKER = '<!-- expectrail-gate:v0 -->'
IDENTITY_REASON = 'GitHub did not bind the capture workflow to the current merge commit'
STALE_REASON = 'Superseded capture or pull request'
