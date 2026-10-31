## Confirmed Facts
- The feature is titled “Password Reset.”
- Users can request a password-reset link by email.
- Each reset link can be used only once.
- Reset links must expire after a reasonable time.
- The existing password remains valid until the reset succeeds.
- The system must handle repeated password-reset requests appropriately.

## Ambiguities
- “Users” is not scoped: it is unclear whether this includes all account types, disabled accounts, unverified accounts, or only active accounts.
- “by email” does not specify the request interface, delivery provider, email contents, or behavior when the address is unknown.
- “used only once” does not define whether a link is consumed on page visit, reset submission, or only after a successful password change.
- “a reasonable time” has no explicit expiration duration or timezone/clock policy.
- “The existing password remains valid until the reset succeeds” does not define what happens after token expiration, failed attempts, or partial/reset failures.
- “Handle repeated requests appropriately” does not specify whether earlier links are invalidated, whether all valid links remain usable, rate limits, notification behavior, or the expected response to repeated requests.

## Clarification Questions
- What account types may request a reset, and should disabled, unverified, or nonexistent accounts receive the same response?
- What is the reset-request endpoint or UI flow, and should requests for unknown email addresses return an indistinguishable response?
- How long should reset links remain valid (for example, 30 or 60 minutes)?
- Should a newer reset request invalidate all previously issued links for that account, or should each unexpired link remain usable?
- When exactly is a link consumed, and should failed password validation or failed reset attempts preserve it?
- What password policy and confirmation requirements apply to the new password?
- Should successful reset invalidate existing sessions, refresh tokens, or other active credentials?
- What rate limits, cooldowns, audit events, and email notifications are required for repeated requests?
- What should happen if email delivery fails or the reset is attempted after expiration?

## Assumptions
- Reset links will contain an unguessable, single-use token and will be delivered through the account’s registered email address.
- A link is considered used only after a successful password reset, so the existing password remains valid through invalid or failed attempts.
- Expired or already-used links will be rejected without changing the password.
- The reset-request response will avoid revealing whether an email address is registered.
- Repeated requests will be rate-limited and will invalidate earlier outstanding links, pending confirmation.

## Summary
The requirement establishes the core password-reset behavior but leaves token lifetime, repeated-request semantics, account eligibility, and security controls undecided. Confirm the expiration period, token invalidation/consumption rules, request responses, password policy, and rate-limiting requirements before implementation.
