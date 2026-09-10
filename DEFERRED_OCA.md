# Prerequisites before installing the suite

**Superseded 2026-09-06.** This file used to describe the OCA-STUB workaround
that let the suite install without its dependencies. That workaround has been
**removed** during the merge: the modules now declare their real dependencies
again, and every `OCA-STUB` marker is gone (`grep -rn "OCA-STUB" .` returns
nothing).

The merged, deployable tree is `Previous Edited Fixed Versions/`.
`odoo_v18_sec_suite/` is the upstream reference copy and is untouched.

## Nothing will install until these three are in place

**1. OCA `auditlog`** — required by `sec_audit_locker`
**2. OCA `base_tier_validation`** — required by `sec_override_engine`

Pinned to the versions the suite was verified against, field by field
(`tier.definition` 12 fields, `auditlog.rule` 8, `auditlog.log`/`.line` 13):

| Module | Repo | Version | Commit |
|---|---|---|---|
| `auditlog` | `OCA/server-tools` @ `18.0` | 18.0.2.0.9 | `91c5c3678e80ddb137bcedecf4e118dfb4a573f0` |
| `base_tier_validation` | `OCA/server-ux` @ `18.0` | 18.0.3.4.1 | `a71545a5efba4b44bd047a3e44db24403e7a82e9` |

```
git clone -b 18.0 --depth 1 https://github.com/OCA/server-tools.git
git clone -b 18.0 --depth 1 https://github.com/OCA/server-ux.git
```

Copy `auditlog` and `base_tier_validation` into
`C:\Program Files\Odoo 18\server\custom addons`.

**3. `py_webauthn`** — required by `sec_webauthn_auth`

```
"C:\Program Files\Odoo 18\python\python.exe" -m pip install webauthn==2.2.0
```

Run **elevated**. Unelevated, pip prints *"Defaulting to user installation"* and
lands in `%APPDATA%\Python`, which the service account
(`NT AUTHORITY\LocalService`) cannot read — the module then still reports the
dependency missing, with nothing in the log to say why.

### Use `==2.2.0`, not bare `webauthn`

Odoo 18 pins `cryptography==42.0.8` and `pyopenssl==24.1.0`, and pyOpenSSL
24.1.0 caps `cryptography<43`. py_webauthn moved past that:

| Version | Requires | Usable here |
|---|---|---|
| 2.2.0 | cryptography (unpinned) | **yes** |
| 2.5.0–2.7.x | cryptography>=43.0.3 | no — breaks Odoo's pyOpenSSL pin |
| 2.8.0 | cryptography>=46.0.0 | no |
| 3.0.0 | cryptography>=49.0.0 | no |

Bare `pip install webauthn` pulls 3.0.0 and upgrades Odoo's TLS stack
underneath it. The only API lost below 2.5.0 is the `require_user_presence`
keyword, and losing it costs nothing: in 2.2.0 the presence check is
*unconditional*, raising on `not auth_data.flags.up` in both ceremonies with no
way to disable it. `models/webauthn_verify.py` carries this reasoning at the
call site.

## Install order

Update Apps List, then activate **`sec_forensic_reporting`** — it sits at the
top of the dependency graph and pulls the other eight in the correct order.
