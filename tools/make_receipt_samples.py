"""Write the Verify page's two test receipts (docs/verify/samples/), signed by a throwaway key.

    python3 -m tools.make_receipt_samples [--issued 2026-11-15T00:00:00Z]

A new Ed25519 key is generated for each run, used to sign, and never written: only its public half
goes into the test trust store. These receipts show the page working. They say nothing about any game,
and the key is not an Expectrail issuer key (Expectrail has none yet: signing in CI waits on #255).
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from expectrail import receipt as rc

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "verify" / "samples"


def digest(label: str) -> str:
    return hashlib.sha256(f"expectrail test receipt: {label}".encode()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.make_receipt_samples")
    parser.add_argument("--issued", default="2026-11-15T00:00:00Z")
    parser.add_argument("--out", type=Path, default=OUT, help="folder to write into (default docs/verify/samples)")
    args = parser.parse_args(argv)
    out = args.out
    issued = datetime.fromisoformat(args.issued.replace("Z", "+00:00")).astimezone(timezone.utc)
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    kid = "throwaway-test-key-" + issued.strftime("%Y%m%d")
    stamp = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    checks = ["stays-on-ground", "lands-after-jump"]
    base = {
        "format": rc.FORMAT, "issuerKeyId": kid, "repository": "Expectrail/Expectrail",
        "baseSha256": digest("base"), "headSha256": digest("head"), "buildSha256": digest("build"),
        "policySha256": digest("policy"), "routeSetSha256": digest("routes"),
        "versions": {"verifier": "test", "adapter": "test", "observer": "test"},
        "evidence": {"grade": "full", "capabilities": ["frames", "engine-record"],
                     "artifacts": {"frames": digest("frames"), "trace": digest("trace")}},
        "coverage": {"required": checks, "exercised": checks, "results": {c: "pass" for c in checks}},
        "decision": "accept", "findings": [], "cost": {"usd": 0},
        "issuedAt": stamp(issued), "expiresAt": stamp(issued + timedelta(days=7)),
        "algorithm": rc.ALGORITHM, "publicKey": public,
    }
    reject = copy.deepcopy(base)
    reject["coverage"]["results"]["stays-on-ground"] = "fail"
    reject["decision"] = "reject"
    reject["findings"] = [{"id": "stays-on-ground", "summary": "test finding: the player is drawn inside the ground"}]
    out.mkdir(parents=True, exist_ok=True)
    rc.write_receipt(base, key, out / "test-receipt-accept.json")
    rc.write_receipt(reject, key, out / "test-receipt-reject.json")
    store = {"format": rc.TRUST_STORE_FORMAT,
             "note": "A throwaway test key for the Verify page's samples. Its private half was discarded after "
                     "signing. It is not an Expectrail issuer key and proves nothing about any game.",
             "keys": [{"id": kid, "publicKey": public}]}
    (out / "test-trust-store.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    del key
    print(f"wrote {out}: two receipts signed by {kid}, valid until {base['expiresAt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
