## Confirmed Facts
- The feature is a password-reset flow.
- Users can request a password-reset link by email.
- Each reset link can be used only once.
- Reset links must expire after a reasonable time.
- The existing password remains valid until a reset succeeds.
- Repeated password-reset requests must be handled appropriately.

## Ambiguities
- “by email” does not specify whether users identify themselves with an email address only, whether the address must be verified, or what response is shown for unknown accounts; the product and security owners should resolve this.
- “used only once” does not define whether a link is consumed when opened, when a reset form is submitted, or only after a successful password change; the security owner should resolve this.
- “reasonable time” does not provide an expiration duration or whether expiration is measured from request creation, delivery, or last request; the security owner, product owner, and applicable security policy should resolve this.
- “The existing password remains valid until the reset succeeds” does not define what counts as success, including validation failures, partial failures, concurrent requests, or session/token invalidation; the security owner should resolve this.
- “Handle repeated requests appropriately” does not specify whether requests invalidate prior links, rate-limit or throttle users, consolidate emails, or return uniform responses; the product and security owners should resolve this.
- The requirement does not specify password policy, token strength, transport protection, audit logging, or notification behavior; security/compliance policy and the product owner should resolve these.

## Clarification Questions
- What identifier should users submit, and should the system require a verified email address? (Product and security owners.)
- What response should be returned for both existing and unknown email addresses to prevent account enumeration? (Security owner.)
- At what exact event is a reset link considered used, and what happens after a failed submission? (Security owner.)
- What expiration duration and time basis should apply to reset links? (Security owner and applicable security policy.)
- Does issuing a new link invalidate all previous links, only the immediately previous link, or none? (Product and security owners.)
- What rate limits, cooldowns, and email-delivery behavior should apply to repeated requests? (Security owner and product owner.)
- What password requirements apply, and should successful reset invalidate active sessions, remembered devices, or other reset tokens? (Security owner and product owner.)
- What audit events, user notifications, and compliance retention requirements are required? (Security/compliance owners.)

## Assumptions
- The reset link will contain a cryptographically secure, unguessable, server-validated token.
- The token will be transmitted only through the user’s email and over HTTPS when redeemed.
- A link is consumed only after a successful password change, so failed validation does not unintentionally invalidate the user’s recovery path.
- The reset flow will avoid revealing whether an email address has an account.
- New reset requests will be rate-limited, and the product will choose a defined policy for invalidating older links.

## Summary
The requirement establishes the core password-reset behavior but leaves token lifecycle, expiration, repeat-request handling, account-enumeration protection, and password/session policies undecided. Product and security owners, with compliance where applicable, must define those rules before implementation.
