// Release tag helpers that scripts/release/changelog.mjs imports. Copied from
// arcforgelabs/flow scripts/release/release.mjs at 1148280 (flow#197): only
// the tag parsing and ordering. The rest of Flow's release.mjs belongs to its
// release train, which Dictate has not copied yet (#145).
//
// Versions are calendar versions YYYY.M.N, where N is a count of releases in
// the month (docs/release-versioning.md). A stable release is vYYYY.M.N (no
// leading zeros) and a beta is vYYYY.M.N-beta.B, where the beta number
// belongs to the upcoming stable version. A correction is vYYYY.M.N-C (the
// older releases' -K): a fix of a published stable release. C counts from 1,
// and a correction comes after its stable release and before the next
// version. The npm shim tags of the old unstable lane,
// vYYYY.M.N-unstable.<run>.<attempt>, are not release tags.

const BASE = /^(20\d{2})\.([1-9]|1[0-2])\.([1-9]\d*)$/;
const TAG = /^v(20\d{2}\.(?:[1-9]|1[0-2])\.[1-9]\d*)(?:-beta\.([1-9]\d*)|-([1-9]\d*))?$/;

export class ReleaseError extends Error {}

export function parseBaseVersion(version) {
  const match = BASE.exec(String(version ?? ""));
  if (!match) throw new ReleaseError(`"${version}" is not a calendar version YYYY.M.N (no leading zeros)`);
  return { version: match[0], parts: [Number(match[1]), Number(match[2]), Number(match[3])] };
}

// A release tag: its version, base version, channel, beta number and
// correction number. A correction's channel is stable.
export function parseTag(tag) {
  const match = TAG.exec(String(tag ?? ""));
  if (!match) throw new ReleaseError(`"${tag}" is not a release tag (vYYYY.M.N, vYYYY.M.N-beta.B or vYYYY.M.N-C)`);
  const base = match[1];
  const beta = match[2] ? Number(match[2]) : null;
  const correction = match[3] ? Number(match[3]) : null;
  const channel = beta ? "beta" : "stable";
  return {
    tag: match[0],
    version: beta ? `${base}-beta.${beta}` : correction ? `${base}-${correction}` : base,
    base,
    channel,
    beta,
    correction,
    branch: `release/${base}`,
    npmDistTag: channel === "beta" ? "beta" : "latest",
    prerelease: channel === "beta",
  };
}

// Oldest first: a beta, then its stable release, then its corrections.
export function compareTags(a, b) {
  const [x, y] = [parseTag(a), parseTag(b)];
  const rank = (release) => (release.beta ? release.beta - Number.MAX_SAFE_INTEGER : (release.correction ?? 0));
  return compareBase(x.base, y.base) || rank(x) - rank(y);
}

export function compareBase(a, b) {
  const [x, y] = [parseBaseVersion(a).parts, parseBaseVersion(b).parts];
  for (let index = 0; index < 3; index += 1) if (x[index] !== y[index]) return x[index] - y[index];
  return 0;
}
