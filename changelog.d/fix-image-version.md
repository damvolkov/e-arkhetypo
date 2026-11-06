### infra

- `jobs/release/image.yml`: the image build gets the tag's version (`build-args: VERSION`) and `docker/metadata-action`
  the tag as its semver value — under `workflow_dispatch` there is no tag ref, so the `:X.Y.Z` tag was never pushed
  (e-organon `:0.8.0` not found) and the package inside said 0.0.0.

### projects

- `python/{api,graph}/Dockerfile`: `ARG VERSION` → `UV_DYNAMIC_VERSIONING_BYPASS` at install (the build context has
  no `.git`). Verified on e-organon: `--build-arg VERSION=9.9.9` → the installed version is 9.9.9.
