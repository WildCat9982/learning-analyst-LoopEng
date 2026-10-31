## Confirmed Facts
- Workspace owners can invite someone to join their workspace by email.
- Accepting an invitation adds the person to the workspace as a member.
- Each invitation link can be accepted only once.
- Each invitation expires after seven days.
- Workspace owners can cancel pending invitations.
- Owners can see which invitations are still awaiting a response.
- The system must handle invitations sent to existing members appropriately.
- The system must handle repeated invitations appropriately.

## Ambiguities
- "by email" does not specify whether the invitee must already have an account, whether invitations can be sent to multiple recipients, or what email validation is required. Decision owner: Product, with Security input.
- "adds the person to the workspace as a member" does not define when membership takes effect, whether the invitee must authenticate as the invited email address, or what happens if the invitee belongs to another role or workspace. Decision owner: Product and Security.
- "accepted only once" does not define whether a second acceptance attempt should show an error, redirect to the workspace, or be treated as already completed. Decision owner: Product.
- "expires after seven days" does not define whether expiry is measured from creation or delivery, the exact cutoff and timezone, or whether owners can resend or extend an expired invitation. Decision owner: Product and Engineering.
- "cancel a pending invitation" does not define whether cancellation invalidates an already-issued link immediately, whether cancellation can be reversed, or what status is shown afterward. Decision owner: Product and Security.
- "which invitations are still waiting for a response" does not define the invitation fields, sorting, pagination, visibility, or whether expired and canceled invitations appear. Decision owner: Product and Privacy/Compliance.
- "Handle invitations to existing members ... appropriately" does not specify whether the system should reject, no-op, notify, or replace an existing membership invitation. Decision owner: Product.
- "repeated invitations appropriately" does not define whether duplicates are blocked, merged, resent, rate-limited, or tracked as separate invitations. Decision owner: Product, with Security input.
- The requirement does not specify authorization boundaries, such as whether all workspace owners may invite, whether there are invitation limits, or how abuse is prevented. Decision owner: Product and Security.
- The requirement does not specify the invitation delivery, acceptance, and failure user experiences or notification content. Decision owner: Product and Design.

## Clarification Questions
- Must invitees have an account already, and must acceptance verify access to the invited email address? Decision owner: Product and Security.
- Can an owner invite one email at a time or multiple addresses in one action, and what email formats or domains are allowed? Decision owner: Product.
- From which event is the seven-day expiration calculated, and what timezone/precision defines the cutoff? Decision owner: Product and Engineering.
- What should happen when an expired invitation is opened, and may an owner resend or renew it? Decision owner: Product.
- What should happen when a canceled link is opened, and is cancellation immediately enforced? Decision owner: Product and Security.
- What response should a user receive when accepting an already-used invitation? Decision owner: Product.
- How should invitations to existing members behave: reject, no-op, notify, or create a separate record? Decision owner: Product.
- How should repeated invitations to the same email and workspace behave, including pending, expired, canceled, and accepted states? Decision owner: Product.
- Which invitation statuses and fields should owners see, and should expired/canceled invitations remain visible? Decision owner: Product and Privacy/Compliance.
- Are there invitation quotas, rate limits, audit-log requirements, or abuse controls? Decision owner: Security and Compliance.
- What roles or permissions can the new member receive, and what happens if the invitee already has a different role? Decision owner: Product and Security.
- What email provider, template, sender identity, localization, and delivery/retry behavior are required? Decision owner: Product and Engineering.

## Assumptions
- Only authorized workspace owners can create or cancel invitations for their workspace.
- An invitation is scoped to one workspace and one email address.
- Acceptance requires a secure, unguessable invitation link and associates the resulting membership with the invited email identity.
- A pending invitation is one that has been created, has not been accepted or canceled, and has not expired.
- Membership is created atomically with successful acceptance, and a used link cannot create another membership.
- The initial member role is the workspace's default member role unless Product specifies otherwise.
- Existing-member and duplicate-invitation behavior will be decided before implementation rather than inferred from the status list.
- Invitation events should be auditable, subject to applicable privacy and retention policies.

## Summary
The core flow and lifecycle requirements are clear: owners create email invitations, invitees accept once within seven days, owners can cancel invitations, and pending invitations are visible. Product, Security, Compliance, Design, and Engineering must still define identity verification, duplicate/existing-member behavior, lifecycle cutoff and UI semantics, authorization and abuse controls, and delivery details.