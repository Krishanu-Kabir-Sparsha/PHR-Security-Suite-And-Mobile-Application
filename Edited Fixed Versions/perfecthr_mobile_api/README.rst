=================================
Perfect HR - Mobile API
=================================

REST endpoints shaped for the Perfect HR Flutter app. Odoo has no mobile-shaped
aggregates of its own, and the app is a pure API consumer, so without this
module the app can only ever show mock data.

Endpoints
=========

============================================  ======  ==================================
Path                                          Method  Purpose
============================================  ======  ==================================
``/api/mobile/v1/auth/login``                 POST    login + password -> token pair
``/api/mobile/v1/auth/refresh``               POST    rotate a refresh token
``/api/mobile/v1/auth/logout``                POST    revoke the presented token
``/api/mobile/v1/me/home``                    GET     E-01 Employee Home aggregate
``/api/mobile/v1/me/authenticators``          GET     WebAuthn enrolment status + URL
============================================  ======  ==================================

Why bearer tokens and not Keycloak
==================================

The client was designed around Keycloak OIDC + PKCE, but its ``AuthInterceptor``
only ever wanted *a bearer token and a refresh endpoint* -- it does not care who
issues them. Odoo issuing its own therefore removes a whole component from the
stack instead of adding one, and none of the client's completed networking work
is wasted. Open question Q5 (Keycloak coordinates) stops being a blocker.

Why opaque tokens and not JWTs
==============================

A JWT buys stateless verification across many services. There is one service
here, and what we actually need is the opposite property: **revocation**. A row
in a table can be switched off when somebody loses a phone. Revoking a JWT means
running a blocklist, which is the statelessness handed back with extra moving
parts. Only a SHA-256 hash is stored, so reading the table yields nothing usable
-- which matters, because BRD 8.2 already assumes a DBA can read any table.

Refresh tokens rotate: using one revokes it and issues a new pair. A refresh
token that survives its own use can be replayed by whoever captured it, and the
legitimate client would never notice because its token still works too.

The declaration gate, and a hole this module closes
===================================================

``sec_declaration_gateway`` enforces the Unified Declaration in
``ir.http._dispatch``, keyed on ``request.session.uid``. A bearer-token request
carries **no session**, so that hook never fires for mobile traffic. Left alone,
the app would have been a way *around* a control whose entire purpose is to be
unavoidable (BRD FR-1).

``controllers/common.py`` therefore checks it directly, and answers with
``403 {"code": "declaration_required"}`` rather than the gateway's ``303``
redirect to an HTML page, which a JSON client cannot follow and would report as
a parse error.

Authorisation is not weakened by ``auth="public"``
==================================================

The routes are declared ``auth="public"`` because Odoo's ``auth="user"`` means a
*session cookie*, which a mobile client does not have. After the token is
resolved, ``request.update_env(user=...)`` switches the request to that real
Odoo user, so every ORM call runs under their own record rules and ACLs --
including the Plaza RBAC grant guard and the Record Freeze mixin. Nothing in the
request path is sudo'd except the token lookup itself and the single
``hr.employee`` join that establishes "me".

WebAuthn enrolment
==================

The app does not run the ceremony. Android's WebView has no FIDO2 support, so an
embedded enrolment page would show its button and never prompt for a
fingerprint. ``/me/authenticators`` reports status and returns a URL for the app
to open in a real browser (Chrome Custom Tab or external).

That is also the better answer: the credential binds to the same ``rp_id`` as a
desktop enrolment, so a phone enrolled from the app is the *same* credential the
web client sees, and nothing needs ``assetlinks.json`` or an Android signing
fingerprint -- so re-signing the app cannot orphan everyone's credentials.

The page is session-authenticated, so the user signs in once in the browser.
Reported to the client as ``requires_web_session``. Minting a browser session
from a mobile token would be a second authentication path around the declaration
gate, to save one login.

Known limitations
=================

* ``performance`` and ``ai_insight`` are always ``null``. No performance source
  is wired up and there is no AI backend. Null rather than zero is deliberate:
  a new joiner shown "0%" reads it as a bad score, not as missing data.
* Break tracking is not modelled, so ``break_started_at`` is always null and
  the ``on_break`` state is never returned.
* Single tenant. ``tenant_id`` is the company id, sent because the client models
  it and inventing it later would be a breaking change.
* ``pending_items`` covers time off only. Expenses and attendance corrections
  join when their screens do.
