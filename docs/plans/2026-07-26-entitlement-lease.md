# Desktop entitlement lease contract

## User outcome

A paid user can continue local processing for up to seven days without a
network connection. Copying or editing local license files cannot grant access.

## Signed format

The server returns a compact token:

```text
base64url(canonical JSON payload).base64url(Ed25519 signature)
```

Required version 1 claims:

- `claim_version`;
- `iss = mindtype.space`;
- `aud = mindtype-desktop`;
- `sub` account ID;
- `device_id`;
- Unix timestamps `iat` and `exp`;
- `plan`;
- string array `features`;
- object `limits`.

The signature covers the encoded payload exactly. A lease cannot last longer
than seven days. The desktop allows five minutes of forward clock skew for
issuance, but no grace period after expiry.

## Acceptance criteria

- AC1: a valid Ed25519 lease for the current device grants full-license access;
- AC2: tampering, unknown schema, wrong device, wrong destination, future issue
  time, invalid duration, and expiry fail closed;
- AC3: a replacement is verified before the last valid lease is overwritten;
- AC4: every access check revalidates expiry from the signed lease;
- AC5: successful lease adoption deletes the legacy HMAC license cache;
- AC6: an expired or corrupt previously adopted lease cannot silently start a
  new local trial;
- AC7: frozen builds ignore runtime public-key environment variables;
- AC8: the production release fails until its embedded public key is non-empty;
- AC9: legacy HMAC cache remains readable for one compatibility release only;
- AC10: server authoritative denial clears the lease and cached session state.

## Current slice

AC1-AC9 are implemented on the desktop and release-workflow side. AC10 and
issuance through `/api/license/session` require the `mindtype.space` backend
repository and session client.
