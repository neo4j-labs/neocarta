# Supply Chain Security Notes

This note captures the practical controls discussed after the TanStack npm
supply-chain compromise on May 11, 2026. The goal is not to make npm installs
"safe" in the abstract. The goal is to stop fresh malicious publishes from
entering CI automatically, reduce credential exposure when install-time malware
runs, and make dependency changes reviewable.

## DBxCarta Project Controls

DBxCarta is currently a Python package and Databricks job runner. The npm
examples below are still useful as general patterns, but the controls for this
repo are:

- Treat `uv.lock` as the dependency source of truth.
- Run `uv lock --check` in CI so manifest and lockfile drift fails fast.
- Run `uv sync --frozen --extra test` in CI so dependency resolution cannot
  change during validation.
- Build package artifacts with `uv build --sdist --wheel`.
- Inspect built artifacts with `scripts/security/artifact_audit.py inspect`
  before they are treated as releasable.
- Generate `dist/supply-chain-provenance.json` with
  `scripts/security/artifact_audit.py provenance` for review evidence.
- Use Renovate's PyPI minimum release age to delay normal dependency updates by
  3 days.

The important Databricks-specific risk is runtime dependency resolution. The
uploaded DBxCarta wheel can still cause Databricks to resolve its dependencies
from package indexes unless the runtime is pointed at a reviewed artifact set.
The recommended next hardening step is a UC Volume wheelhouse generated from
the reviewed lockfile, with Databricks jobs installing from that wheelhouse
instead of resolving directly from public PyPI.

The current `dbxcarta-submit publish-wheels` flow is convenient but not ideal for
release control because it bumps the version, builds the wheel, and uploads it
in one operation. Reviewed release flows should keep build evidence from CI and
eventually submit Databricks jobs by explicit artifact version or hash.

Credential policy for this repo:

- Neo4j credentials stay in Databricks secret scopes.
- `.env` values forwarded to job parameters must be non-secret configuration.
- Add new secret names to the runner's secret handling before using them in
  job runtime configuration.
- Do not publish `.env`, local outputs, wheel caches, or Databricks profile
  files in package artifacts.

## Why Lockfiles Help

Package manifests usually describe ranges:

```json
{
  "dependencies": {
    "@tanstack/router": "^1.100.0"
  }
}
```

Without a lockfile, a clean install can resolve whatever version satisfies that
range at install time. If a malicious version is published later and still
matches the range, CI can install it without any source change in this repo.

A lockfile changes the behavior. It records exact versions and integrity hashes.
An immutable install then refuses to update the lockfile during CI.

Use the package-manager equivalent:

```bash
npm ci
pnpm install --frozen-lockfile
yarn install --immutable
bun install --frozen-lockfile
```

This means a new malicious publish does not enter the build just because it was
published upstream. It enters only when a dependency update changes the lockfile.
That gives review, tests, and automated policy checks a chance to run.

## Why Immutable Installs Matter

Do not use normal install commands in CI for application builds:

```bash
npm install
pnpm install
yarn install
bun install
```

Those commands can update dependency resolution as part of the install flow. In
CI, installs should be reproducible. If the lockfile and manifest disagree, the
build should fail instead of silently choosing newer dependency versions.

## Version Quarantine

Version quarantine means newly published package versions are not consumed until
they have aged for a defined period, such as 24 hours, 72 hours, or 7 days.

This helps because many npm compromises are detected quickly. In the TanStack
case, public detection happened within roughly 20 minutes. A quarantine window
would likely have prevented many automated builds from consuming the compromised
versions.

Prefer quarantine by time, not by "one version behind":

- Attackers can publish several malicious versions quickly.
- A single compromised package can update multiple times before detection.
- Staying behind blindly can also delay legitimate security fixes.
- A time delay is easier to reason about and enforce.

Recommended baseline:

- Application repos: 3 day minimum release age for npm updates.
- Critical production systems: 7 day minimum release age unless manually
  approved.
- Security patches: allow explicit override after review.
- DBxCarta Python dependencies: 3 day minimum release age for PyPI updates,
  with explicit review for urgent security fixes.

## Renovate Configuration

Renovate supports minimum release age. For npm, Renovate uses npm's
`--before=<date>` behavior during lockfile generation, which also helps avoid
new transitive dependencies that are younger than the cooldown window.

Example `renovate.json`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "packageRules": [
    {
      "matchDatasources": ["npm"],
      "minimumReleaseAge": "3 days",
      "internalChecksFilter": "strict"
    }
  ]
}
```

For stricter repos, use `"7 days"`.

For this repo, `renovate.json` applies the same quarantine concept to PyPI
dependencies with `"matchDatasources": ["pypi"]`.

## Registry Proxy And Firewall Options

A registry proxy can help, but there are two different capabilities:

- Caching proxy: stores package artifacts locally and provides a single registry
  endpoint.
- Policy firewall: blocks or delays packages based on rules such as package age,
  package name, version, license, maintainer, or vulnerability data.

Free and open-source options:

- Verdaccio: free, self-hosted npm registry proxy. It can proxy npmjs.org and
  cache downloaded packages. Good for a local/private npm registry and basic
  pull-through caching.
- npm-registry-firewall: free, self-hosted npm registry proxy with filtering
  rules. It supports an `age` rule that can implement quarantine, for example
  allowing only versions older than 5 days.
- Sonatype Nexus Repository Community Edition: self-hosted repository manager
  with npm support. Useful when the team wants a broader artifact repository,
  not just npm. Verify feature availability for the current edition before
  depending on policy controls.

Commercial tools may have trials, open-source allowances, or limited free tiers,
but those change over time. Treat hosted "free tier" claims as something to
verify during tool selection.

## CI Release Workflow Controls

For packages published by this repo or related repos:

- Do not run fork-controlled code in `pull_request_target` workflows.
- Do not restore dependency caches in release workflows.
- Scope `id-token: write` only to the publish job that needs it.
- Put publish jobs behind protected branches, protected tags, or protected
  environments.
- Pin third-party GitHub Actions by full commit SHA in sensitive workflows.
- Use read-only tokens for dependency installation.
- Revoke unused npm automation tokens.
- Keep the npm maintainer list small and require strong 2FA.

Trusted publishing and provenance are useful, but they are not enough by
themselves. If the trusted workflow is compromised, a malicious package can still
be published with valid provenance. Treat provenance as evidence for audit and
detection, not as a guarantee that the artifact is safe.

## References

- TanStack postmortem: https://tanstack.com/blog/npm-supply-chain-compromise-postmortem
- npm trusted publishing docs: https://docs.npmjs.com/trusted-publishers/
- Renovate minimum release age docs: https://docs.renovatebot.com/key-concepts/minimum-release-age/
- Verdaccio: https://www.verdaccio.org/
- npm-registry-firewall: https://www.npmjs.com/package/npm-registry-firewall
- OpenJS npm publishing guidance: https://openjsf.org/blog/publishing-securely-on-npm
