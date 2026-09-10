# Installing on an on-premises Odoo CE V18 VM

## What you are installing

One module: **`sec_plaza_rbac`** — the Plaza Model role catalog, its access
matrix, the segregation-of-duties checker, and the non-standard grant guard.
That is Phase 0 of the eight-module suite. The record freeze engine, the Locker,
the override workflow and WebAuthn do **not** exist yet, so installing this does
not yet freeze any records or block any edits.

It has never been run against a database. Install it on a **test VM with a copy
of production data first**, not on production. It overrides `res.users.write()`,
which means a defect here can lock you out of assigning user permissions.

## 1. Copy the module to the VM

The addon directory is `addons/sec_plaza_rbac/` inside the download. Only that
directory goes on the server; `docs/`, `tools/`, `PROGRESS.md` and
`BUILD_STATE.json` stay in your project repo.

```bash
# from your workstation, after unzipping
scp -r sec_plaza_rbac odoo@your-vm:/tmp/

# on the VM
sudo mv /tmp/sec_plaza_rbac /opt/odoo/custom-addons/
sudo chown -R odoo:odoo /opt/odoo/custom-addons/sec_plaza_rbac
```

Use whatever custom addons path your VM already has. Common locations:
`/opt/odoo/custom-addons`, `/mnt/extra-addons` (Docker), `/usr/lib/python3/dist-packages/odoo/addons` (package install — avoid putting custom code here).

## 2. Make sure the path is in your Odoo config

```bash
sudo nano /etc/odoo/odoo.conf
```

```ini
[options]
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo/custom-addons
```

If you added the path, restart: `sudo systemctl restart odoo`.

## 3. Install the module

**Option A — command line (recommended, shows errors immediately):**

```bash
sudo systemctl stop odoo
sudo -u odoo odoo -c /etc/odoo/odoo.conf -d YOUR_DB -i sec_plaza_rbac --stop-after-init
sudo systemctl start odoo
```

Read the output. Because this has never been executed, expect the possibility of
load errors on the first attempt — a bad field reference or a view attribute
V18 rejects. The command above tells you the file and line; a UI install just
shows a generic error.

**Option B — through the UI:**

1. Log in as an administrator.
2. Enable developer mode: Settings → General Settings → Developer Tools →
   Activate the developer mode.
3. Apps → Update Apps List → confirm.
4. Clear the "Apps" filter, search `Plaza`, and click Install on
   *Security Suite - Plaza Model RBAC*.

## 4. Run the test suite

This is the step that promotes the module from "written" to "verified". Do it on
a scratch database.

```bash
sudo -u odoo odoo -c /etc/odoo/odoo.conf -d TEST_DB \
    -i sec_plaza_rbac --test-enable --test-tags /sec_plaza_rbac --stop-after-init
```

31 tests should run. Report whatever fails — that output is exactly what the
next build session needs to fix things and mark P0-2/P0-3 done honestly.

## 5. First things to check in the UI

- A new top-level **Security Suite** menu appears (you may need to be in the
  *Plaza RBAC / Viewer* group or be a superuser).
- **Security Suite → Plaza RBAC → Role Catalog** lists 15 roles, each with a
  description and an access matrix on the form.
- **Security Suite → Segregation of Duties → Run SoD Scan** produces a scan.
  On a fresh database with no role assignments it should come back clean.

## Important: the grant guard will change how you assign permissions

Once installed, assigning a user any security group that is **not** backed by a
Plaza role raises a validation error telling you to raise a Grant Exception
first. That is deliberate (PRD US-2.1), but it will surprise administrators.

Two escape hatches exist:

- **Grant Exception:** Security Suite → Plaza RBAC → Grant Exceptions → create,
  fill the justification, Approve, then make the assignment.
- **Context bypass**, for scripted/migration work only:

  ```python
  user.with_context(plaza_bypass_grant_check=True).write({"groups_id": [(4, group.id)]})
  ```

If it locks you out during testing, uninstall from the shell:

```bash
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d YOUR_DB
>>> env["ir.module.module"].search([("name","=","sec_plaza_rbac")]).button_immediate_uninstall()
>>> env.cr.commit()
```

## OCA dependencies

`sec_plaza_rbac` needs none. Later modules will need these on the same addons
path, from the `18.0` branches:

```bash
cd /opt/odoo/custom-addons
git clone -b 18.0 --depth 1 https://github.com/OCA/server-tools.git
git clone -b 18.0 --depth 1 https://github.com/OCA/server-ux.git
```

Then add those directories to `addons_path`. Pin them to a specific commit
rather than tracking branch HEAD — see `docs/OCA_V18_COMPATIBILITY.md`.
