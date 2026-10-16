# image — ghcr, no credentials

The `image` job logs into ghcr with the built-in `GITHUB_TOKEN`; there is no secret to create. Once:

1. Enable: `gh variable set PUBLISH_IMAGE --body true` (the feature also needs the `stack.docker` choice:
   the repo must carry a `Dockerfile`).
2. **First push of a new package**: GitHub asks who may let Actions write it — approve once in
   the package settings, or pre-approve the repository. Subsequent runs are silent.
3. The package inherits the repository's visibility; make it public if consumers should pull without auth.

Tags: `ghcr.io/<owner>/<brand>:<version>` and `:latest`. Multiple images per repo (e-voice style):
keep one Release workflow per image with its own `<name>-v*` tag scheme.
