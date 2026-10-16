# pypi — trusted publishing (no token, ever)

Once, in the repository and on PyPI:

1. **pypi.org → your project → Publishing → Add trusted publisher**: owner `<you-or-org>`,
   repository `<repo>`, workflow `release.yml`, environment `pypi`. Same for every project name you own.
2. In GitHub, the `pypi` environment may hold approver protection; the OIDC job only needs the
   environment to **exist** with that name (`environment: pypi` in the publish job).
3. Enable: `gh variable set PUBLISH_PYPI --body true`.

Release by hand afterwards: Actions → Release → *Run workflow* → bump `patch|minor|major`, or republish
an existing `v*` tag verbatim. The tag IS the version (`uv-dynamic-versioning`); nothing publishes on a merge.
