## Confirmed Facts
- Users can download the records shown in a report as a CSV file.
- The export must respect the user’s current filters.
- The export must respect the user’s access permissions.
- The CSV must include a header row containing the column names.
- Large exports should run in the background so the user can continue working.
- The user must be notified when the file is ready.
- Download links must remain available for a reasonable time.
- If an export fails, the system must explain what happened and allow the user to try again.

## Ambiguities
- “records shown in a report” is unclear about whether the CSV contains all matching rows or only the current page; for a grouped report, it is also unclear whether it exports grouped results or underlying records. The product owner should define the export scope.
- “current filters” is unclear when a user changes filters after submitting a queued export; the product owner should define whether the job uses submission-time or execution-time filters.
- “access permissions” is unclear if access is revoked after job creation but before download; the security owner should define whether authorization is enforced at request, job execution, and/or download time.
- “Large exports” has no threshold, so different teams could choose different background-processing behavior; the product owner and engineering owner should set the row, size, or duration threshold.
- “Notify the user” is unclear if a job completes while the user is offline or if email/in-app delivery fails; the product owner should define required channels, retry behavior, and fallback status visibility.
- “A reasonable time” is unclear if a link expires while a user is downloading or before an offline user returns; the product owner, with compliance/security input, should define retention and expiry behavior.
- “Explain what happened” is unclear if a failure exposes database or permission details; the security owner should define safe user-facing detail, while the product owner should define actionable error categories.
- “Try again” is unclear if the original filters are stale or permissions changed; the product owner and security owner should define whether retry uses the original snapshot and rechecks authorization or uses the current report state.

## Clarification Questions
- Product owner: Should an export include all rows matching the report query, only rows currently visible on the page, or grouped/aggregated results; how should grouped reports be represented?
- Product owner, with security owner approval: Should filters and report configuration be snapshotted at request time, job-start time, or download time, and when must permissions be rechecked?
- Product owner and engineering owner: What row-count, file-size, or execution-time threshold makes an export background work, and what behavior is required at the boundary?
- Product owner: Which notification channels are required, and what should happen if a queued job completes while the user is offline or notification delivery fails?
- Product owner, with compliance/security policy input: How long should links remain available, what should happen after expiry, and may an active download finish if expiry occurs during transfer?
- Product owner and security owner: Which failure categories and retry guidance should users see, and what technical details must be suppressed to avoid sensitive disclosure?
- Product owner and security owner: Should retry reuse the original export parameters while rechecking authorization, or use the report’s then-current filters and permissions?
- Product owner and engineering owner: Are concurrent-export, size, or frequency limits required, and what user-visible behavior applies when a limit is reached?
- Product owner and engineering owner (optional product-design clarification): If the requirement does not already establish CSV conventions, should the team define encoding, delimiter, quoting, line endings, null representation, and filename rules?

## Assumptions
- Provisionally, pending the product owner’s scope decision, export initiation occurs from an existing report and uses the report’s available columns.
- Provisionally, pending the security owner’s authorization decision, the exported dataset contains only data the requesting user is authorized to access.
- Provisionally, pending the product owner and engineering owner’s threshold decision, exports above a configured large-export threshold run asynchronously and smaller exports may complete synchronously.
- Provisionally, pending product owner and compliance/security retention policy, completed files are stored temporarily and links are removed or invalidated after the approved retention period.
- Provisionally, pending the product owner’s failure-policy decision, a failed export produces no downloadable partial file.
- Provisionally, pending the product owner’s snapshot decision, the export job records the parameters needed to reproduce the requested report state.

## Summary
The requirement defines a permission-aware CSV export with headers, background processing for large jobs, completion notification, temporary download availability, and retryable failures. The product owner, engineering owner, security owner, and applicable compliance policy must settle export scope, snapshot and authorization timing, thresholds, notification and retention behavior, safe error detail, retry semantics, and any optional CSV conventions.
