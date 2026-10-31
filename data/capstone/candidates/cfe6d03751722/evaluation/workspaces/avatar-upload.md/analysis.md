## Confirmed Facts
- Users can upload one avatar image to their profile.
- An uploaded image must be smaller than 2 MB.
- Images must be stored securely.
- The system should accept all common image formats.
- Replacing an avatar should be easy.

## Ambiguities
- “one avatar image” — It is unclear whether each user may retain only one active avatar, whether upload history is allowed, and whether an avatar is optional. Decision owner: Product.
- “smaller than 2 MB” — It is unclear whether the limit is strictly less than 2 MB or inclusive of 2 MB, and whether MB means decimal megabytes or binary mebibytes. Decision owner: Product/Engineering.
- “stored securely” — It does not define required encryption, access controls, isolation, retention, malware scanning, or compliance requirements. Decision owner: Security/Compliance.
- “all common image formats” — The supported format list, MIME/signature validation rules, and handling of animated or oversized images are unspecified. Decision owner: Product/Engineering/Security.
- “Replacing an avatar should be easy” — The expected user flow, permissions, overwrite behavior, and whether replacement is immediate are not defined. Decision owner: Product/UX.

## Clarification Questions
- Should users have exactly one active avatar, and may they remove it or retain prior versions? Decision owner: Product.
- Does “smaller than 2 MB” mean strictly under 2,000,000 bytes, under 2 MiB, or another threshold? Decision owner: Product/Engineering.
- Which image formats must be supported, and should the system normalize, resize, or strip metadata from uploads? Decision owner: Product/Engineering/Security.
- What security controls are mandatory for storage and processing, including encryption at rest/in transit, private access, malware scanning, and retention/deletion? Decision owner: Security/Compliance.
- What should happen when a user uploads a replacement: replace immediately, preserve the old image temporarily, and allow cancellation or recovery? Decision owner: Product/UX.
- Who can view or change an avatar, and are there moderation, privacy, or authorization requirements? Decision owner: Product/Security.

## Assumptions
- Each user has at most one active avatar visible on their profile.
- Uploading a replacement will make the new image active without requiring a separate administrative action.
- The size limit will be enforced before durable storage, subject to the confirmed byte definition.
- Only valid image files, rather than arbitrary files renamed with image extensions, will be accepted.
- Avatar storage will be private by default and served only through authorized application access.

## Summary
The requirement establishes a single profile-avatar upload capability with a size limit, secure storage, broad image-format support, and straightforward replacement. Product, Engineering, UX, Security, and Compliance must still decide the exact size interpretation, supported formats and processing, security controls, lifecycle behavior, and access rules.