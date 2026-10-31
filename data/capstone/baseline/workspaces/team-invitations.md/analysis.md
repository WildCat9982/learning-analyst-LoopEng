## Confirmed Facts
- Workspace owners can invite someone to join their workspace by email.
- Accepting an invitation adds the person to the workspace as a member.
- An invitation link can be accepted only once.
- An invitation expires after seven days.
- Owners can cancel a pending invitation.
- Owners can see which invitations are still awaiting a response.
- The system must handle invitations to existing members appropriately.
- The system must handle repeated invitations appropriately.

## Ambiguities
- “invite someone to join their workspace by email” does not define whether an invitation is sent only to a new account or can target an email associated with an existing account.
- “An invitation link can be accepted only once” does not specify whether accepting, canceling, or expiration permanently invalidates the link, nor whether concurrent acceptance attempts must be prevented atomically.
- “expires after seven days” does not define whether the period starts when the invitation is created or sent, the exact expiration timestamp/time zone, or whether expiration is inclusive.
- “Owners can cancel a pending invitation” does not define whether cancellation is available until acceptance/expiration only, whether the recipient is notified, or whether a canceled link can ever be restored.
- “Show owners which invitations are still waiting for a response” does not define the required interface, fields, scope, or whether expired invitations count as pending.
- “Handle invitations to existing members and repeated invitations appropriately” does not define whether the system should reject, reuse, replace, or allow multiple invitations, or what response and notifications are expected.
- “adds the person to the workspace as a member” does not specify whether the invitee must authenticate as the invited email address or whether an invitation can be transferred.

## Clarification Questions
- Can owners invite both existing users and people who do not yet have accounts? What happens when the invited email already belongs to a workspace member?
- What should happen when an owner sends a repeated invitation to the same email/workspace: reject it, resend the existing invitation, replace it, or create another pending invitation?
- Are duplicate invitations allowed across different owners, and what response/status should the owner receive for duplicates?
- Does the seven-day expiration begin at creation or delivery, and what timezone/precision defines the deadline?
- What states should an invitation have (for example pending, accepted, canceled, expired), and should expired invitations remain visible in history?
- Must acceptance require the authenticated account’s email to match the invited email, and how should unauthenticated recipients complete acceptance?
- What notification should be sent on invitation, cancellation, acceptance, expiration, and resend?
- What should happen if cancellation and acceptance occur at nearly the same time?
- Which owners may view or cancel invitations, and should they see invitations created by other owners?
- What fields and actions are required in the owner-facing list of outstanding invitations?

## Assumptions
- Only workspace owners may create, view, or cancel invitations unless authorization rules say otherwise.
- An invitation is scoped to one workspace and one invited email address.
- Acceptance requires the recipient to prove control of the invited email and prevents adding the same person more than once.
- A pending invitation becomes invalid when accepted, canceled, or expired.
- Expired and canceled invitations are not considered to be waiting for a response.
- Repeated invitations to the same workspace and email are treated as one pending invitation rather than creating duplicate active links.

## Summary
The requirement establishes an email-based, single-use, seven-day workspace invitation flow with owner cancellation and pending-invitation visibility. Decisions are still needed for identity verification, invitation state transitions, duplicate handling, expiration timing, notifications, permissions, and the owner-facing UI/API details.
