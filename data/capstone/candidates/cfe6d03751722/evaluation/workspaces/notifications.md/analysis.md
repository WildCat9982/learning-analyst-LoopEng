## Confirmed Facts
- The product must send notifications by email and within the app.
- Users must be able to disable ordinary email notifications.
- Urgent notifications must arrive quickly.
- Related notifications must be grouped sensibly.
- Unread in-app notifications must be retained for 30 days.

## Ambiguities
- "Send notifications by email and in the app." It is unclear which notification types use which channels, whether delivery is simultaneous or configurable, and whether users can control in-app notifications. Decision owner: Product; security/compliance may constrain channel use.
- "Users can disable ordinary email notifications." "Ordinary" is undefined, and it is unclear whether disabling applies to all non-urgent email, selected categories, or individual messages; it is also unclear whether urgent email is mandatory. Decision owner: Product, with Compliance/Security for legally or operationally required messages.
- "Urgent notifications must arrive quickly." "Urgent" lacks criteria, and "quickly" lacks a measurable delivery target, success rate, retry policy, and treatment of provider or device failures. Decision owner: Product and SRE/Operations.
- "Group related notifications sensibly." The grouping rules, grouping window, user experience, and whether grouping applies to email, in-app notifications, or both are unspecified. Decision owner: Product and UX.
- "Retain unread in-app notifications for 30 days." It is unclear whether retention is exactly 30 days from creation or last update, what happens when a notification is read, whether read notifications have a separate retention period, and whether legal holds or audit requirements override deletion. Decision owner: Product, with Compliance/Legal.

## Clarification Questions
- Which notification categories and events are in scope, and which channels should each category use? Decision owner: Product.
- What qualifies as ordinary versus urgent, and may users disable or otherwise control urgent notifications? Decision owner: Product, with Compliance/Security for mandatory communications.
- What measurable delivery SLA defines "quickly" for urgent notifications, including acknowledgement, retries, and provider outage handling? Decision owner: Product and SRE/Operations.
- How should related notifications be identified and grouped, over what time window, and separately for email versus in-app delivery? Decision owner: Product and UX.
- Does the 30-day period begin when an in-app notification is created, and should read notifications be deleted immediately, retained separately, or handled another way? Decision owner: Product.
- Are there privacy, consent, accessibility, localization, or regulatory requirements governing notification content, channel selection, opt-out behavior, or retention? Decision owner: Compliance/Legal and Security.

## Assumptions
- Both email and in-app delivery are required, but exact routing is configurable by notification category.
- Users may opt out of ordinary email but not messages that Product or Compliance designates as mandatory or urgent.
- "Quickly" will be converted into an explicit operational SLA before implementation.
- Grouping will be implemented as a user-visible aggregation rather than silent suppression of individual events.
- The 30-day rule applies to unread in-app records measured from their creation time, subject to approved legal or compliance exceptions.

## Summary
The requirement establishes two delivery channels, email opt-out for ordinary messages, expedited handling for urgent messages, grouping, and 30-day unread in-app retention. Implementation still needs decisions on notification taxonomy, opt-out and urgency rules, measurable delivery targets, grouping behavior, retention semantics, and compliance constraints.
