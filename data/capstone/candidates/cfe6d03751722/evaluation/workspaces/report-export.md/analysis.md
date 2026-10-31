## Confirmed Facts
- Users can download the records shown in a report as a CSV file.
- The export respects the user’s current filters and access permissions.
- The CSV includes a header row with column names.
- Large exports run in the background so the user can continue working.
- The user is notified when the file is ready.
- Download links remain available for a reasonable time.
- If an export fails, the user receives an explanation and can try again.

## Ambiguities
- “records shown in a report” could mean only the currently visible page or all records matching the report query; the product owner should define the export scope.
- “current filters” does not specify whether filters are captured at export initiation or reevaluated while the background job runs; product and engineering should define the snapshot behavior.
- “access permissions” does not specify whether permissions are checked only when the export starts or again when the file is generated/downloaded; security should define the enforcement points.
- “Large exports” has no size or processing-time threshold; product and engineering should establish the threshold and expected behavior for smaller exports.
- “Notify the user” does not specify the notification channel, delivery guarantees, or notification contents; product should decide the UX, with security/privacy reviewing exposed details.
- “reasonable time” is undefined; product and compliance/security should specify link expiration, retention, and whether links are revocable.
- “explain what happened” does not define the error detail level or whether sensitive implementation details must be suppressed; product and security should define the user-facing error policy.
- “CSV file” does not specify encoding, delimiter, quoting/escaping, treatment of nulls and special values, or protection against formula injection; engineering and security should define the format and safeguards.

## Clarification Questions
- Should an export include all records matching the report filters, or only records on the currently displayed page? Decision owner: product.
- Are filters and report configuration snapshotted when the user starts the export? Decision owner: product, with engineering input.
- At which points must authorization be revalidated: job creation, record retrieval, file generation, and/or download? Decision owner: security/compliance.
- What record count, file size, or estimated duration qualifies as a large export? Decision owner: product and engineering.
- How should users be notified that an export is ready—for example, in-app notification, email, or both—and what happens if delivery fails? Decision owner: product.
- How long should generated files and download links be retained, and can users revoke them? Decision owner: product, security, and compliance.
- What CSV specification is required, including encoding, delimiter, quoting, null values, line endings, and formula-injection protections? Decision owner: engineering and security.
- What user-facing error categories and retry behavior are required, and should partial files ever be offered? Decision owner: product and engineering.

## Assumptions
- The export is initiated from an existing report and uses that report’s applicable filter state.
- The export contains all authorized records in the report result, rather than only the visible page; this remains to be confirmed by product.
- Authorization is enforced server-side and no unauthorized records are included in generated files.
- A background job provides status tracking and a retriable failure state.
- Download links are authenticated, access-controlled, and expire after a configured retention period.
- The CSV uses a conventional interoperable encoding and safely escapes values; exact rules remain to be confirmed.

## Summary
The requirement establishes an authorized, filter-aware CSV export with asynchronous processing, readiness notification, expiring access, and retryable failure handling. Product, engineering, security, and compliance still need to decide export scope, snapshot and authorization timing, large-export thresholds, notification UX, CSV rules, retention, and error behavior.
