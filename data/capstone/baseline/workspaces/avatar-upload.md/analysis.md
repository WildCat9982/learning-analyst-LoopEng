## Confirmed Facts
- Users can upload one avatar image to their profile.
- An uploaded image must be smaller than 2 MB.
- Images must be stored securely.
- The system must accept all common image formats.
- Users should be able to replace an existing avatar easily.

## Ambiguities
- “one avatar image” could mean one active image per profile, or one upload allowed over the profile’s lifetime; the product owner should settle the intended cardinality and replacement policy.
- “smaller than 2 MB” could mean strictly below 2,000,000 bytes, below 2 MiB, or a UI/API file-size limit measured differently; the product owner and engineering owner should define the user-facing and enforcement limit.
- “stored securely” does not define encryption, access controls, retention, malware scanning, or whether avatars are publicly accessible; the security/privacy owner, together with the platform engineering owner, should specify the required controls and access model.
- “all common image formats” does not specify supported MIME types, file extensions, animated-image behavior, or whether formats are converted during processing; the product owner should define the supported user experience, while the engineering owner should validate feasibility and the security owner should approve safe parsing/processing requirements.
- “Replacing an avatar should be easy” does not specify the user flow, whether replacement is in-place, whether deletion is supported, or what happens if replacement fails; the product/design owner should define the interaction and the engineering owner should define transactional behavior.

## Clarification Questions
- Should “one avatar” mean one active avatar at a time, with replacement permitted indefinitely? The product owner should answer.
- What exact size limit and unit should be enforced: 2,000,000 bytes or 2 MiB (2,097,152 bytes), and is the limit strictly less than that value? The product owner should choose the product rule, and the engineering owner should document the enforcement point.
- Which image formats must be supported, and should unsupported formats return a specific error? Should animated formats be accepted? The product owner should define the supported formats and UX; the security owner should approve the processing of each format; engineering should confirm implementation feasibility.
- What security controls are required for storage and serving, such as encryption at rest, private access, authorization checks, malware scanning, and content-type validation? The security/privacy owner should provide the authoritative security requirements, with platform engineering specifying how they are implemented.
- What replacement and deletion workflow should the profile UI provide, and should the previous image be removed immediately after a successful replacement? The product/design owner should define the workflow and retention expectation; engineering should define atomic replacement and cleanup behavior.
- Are image dimensions, aspect ratio, file naming, resizing, thumbnail generation, or processing-time limits required? The product/design owner should decide product constraints, and engineering should provide technical limits; security should review processing-related risks.
- What should happen when an upload or replacement fails, and should the existing avatar remain unchanged? The product owner should define the user-visible behavior, while engineering should ensure the existing avatar is preserved on failure.

## Assumptions
- Each profile has at most one active avatar, and a user may replace it repeatedly, pending confirmation from the product owner.
- The size check applies to the uploaded file before any transformation and uses a byte-based limit once the product and engineering owners define it.
- The system will validate file content rather than relying only on client-provided extensions or MIME types, subject to security-owner approval.
- A failed replacement will leave the current avatar intact unless the product owner specifies otherwise.
- Avatar access will be limited to authorized profile viewers unless the product owner and privacy/security owner approve public avatars.

## Summary
The core requirement is clear: support one securely stored, replaceable profile avatar subject to a size limit and common image-format support. The product owner must decide user-facing behavior and supported formats, while security/privacy must define storage and access controls; engineering then confirms limits, feasibility, and failure-safe implementation.
