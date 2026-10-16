# docs — GitHub Pages

Once, in the repository:

1. **Settings → Pages → Source: GitHub Actions** (the `pages` job deploys through Actions, not a branch).
2. Enable: `gh variable set DOCS_DEPLOY --body true` — until then the build runs strict but nothing deploys.
3. The repository must be **public** for Pages to serve it; a private repo keeps the deploy inert.

The docs job fails the PR on a broken link or a missing asset (`--strict`), gate or no gate.
