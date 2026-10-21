# Application release version

The frontend package manifest is the application release version source. Settings
and About render `appVersionLabel` from `src/appMetadata.ts`, which imports
`package.json` at build time. The current candidate is `1.0.0-rc.3`, displayed as
`v1.0.0-rc.3`; do not append Beta. The backend Python package version describes
that package independently and is not the patient UI release label.

Before an approved release build, set the agreed candidate version in
`frontend/package.json` and both root package-version fields in
`frontend/package-lock.json` (for example with `npm version <candidate>
--no-git-tag-version` from `frontend`). Review the diff, run checks and commit the
version with its release changes. A local candidate label does not update an
already deployed application: the hosted UI keeps the version embedded in its
own build until an approved deployment replaces it.

Existing repository tags are `v1.0.0-rc.1` and `v1.0.0-rc.2`; historically their
frontend manifest versions differ from their tag names. Do not rewrite those
tags. Starting with this candidate, require the approved release tag name to
match the manifest version embedded in the deployed frontend.

After push/deployment approval, deploy a reviewed commit, verify the deployment
source SHA and displayed version, and perform production acceptance. Only after
separate tag approval, create the matching release tag against that exact
accepted commit SHA. Never select the newest tag at runtime, tag whichever HEAD
happens to be current, or silently reuse an existing tag. If a correction changes
the accepted commit, revalidate that artifact before tagging it. Release metadata
has no runtime GitHub dependency. No tag or deployment is created by a build.
