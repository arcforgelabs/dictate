# Dictate personal ownership transfer

Related: [#135](https://github.com/arcforgelabs/dictate/issues/135) and
[#164](https://github.com/arcforgelabs/dictate/issues/164).

Target: `IAMSamuelRodda/dictate`. Dictate is a Linux-only open-source personal
app, with no official deployment. Source cleanup and actual repository
transfer are distinct; this document does not claim the move has happened.

## Preserve existing consumers and work

Keep every branch, tag, issue, PR, release, asset and signed binary. Preserve
unique local commits/uncommitted work with each checkout owner. Do not reset
shared checkouts or rewrite release history.

Keep `@arcforgelabs/dictate`, its versions/dist-tags and jsDelivr URLs.
Keep Store product `9P5S7747V0BP` and package identity
`ArcForgeLabs.ArcForgeDictate`. Their historical existence does not imply
current Windows support. No npm rename/deprecation, Store API change, package
identity change or replacement release is required for a source transfer.

Keep the old GitHub namespace vacant: recreating `arcforgelabs/dictate`
removes its redirects and can break installed updaters.

## Remaining transfer gates

1. Coordinate central bot routing with the bot fleet owner. Organization-App
   Barnacle/Labeler callers and their orphaned helper/config are removed rather
   than recreated under a personal account. No App key, installation or fleet
   ownership changes here. The fleet owner separately handles central
   ClawSweeper profiles and old-owner Worker/Clownfish jobs before cutover.
2. Inspect current repository identity, integration/webhook and collaborator
   state, environment protections and actual transfer authority. Capture issue
   assignments/types: GitHub removes non-owner assignments, issue types and
   read-only collaborators on organization-to-personal moves. Resolve material
   losses rather than treating them as preservation.
3. Capture all refs and release asset IDs/names/sizes/digests immediately before
   cutover. Confirm old and new URL behavior and installed update compatibility.

The retired Windows runner, Store publication, npm publisher and business docs
mirror are **not** current transfer prerequisites. Their source workflows were
removed rather than recreated under a personal account. A future npm publisher
would need separate validation of its repository binding, independent publish/
dist-tag permissions and supported CLI; this cleanup does not grant that access.

## Cutover and verification

After the remaining gates pass, use GitHub's maintained repository transfer
operation with `new_owner=IAMSamuelRodda`, not a replacement repository.
Observe a pending request rather than blindly resubmitting it.

Compare the canonical repository ID, every captured ref and release asset,
protections and environments. Test anonymous old/new latest/tag APIs and a real
asset download against its captured SHA-256. Exercise existing npm-first update
discovery and GitHub fallback/asset lookup; confirm old Git clone/fetch and
npm/jsDelivr URLs work. Source URLs can then point at the canonical new owner.

No new release or official deployment is part of this move. #164's old Store
certification checklist is historical; this cleanup neither changes the live
listing nor claims that its links/certification are complete. Retain that issue
for an explicit maintainer disposition, not as a Linux pipeline gate.

[GitHub transfer behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository)
