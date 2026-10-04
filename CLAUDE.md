# Project notes for Claude

<!-- gitlab-home: where this repo lives -->
## Where this repo lives (read before pushing)

GitLab is the home of this repository: <https://gitlab.com/nicholaskmitchell/smylte>.
<https://github.com/nicholaskmitchell/smylte> is a mirror that GitLab overwrites whenever `main` changes.

If your `origin` is GitHub (a cloud session, or a contributor's clone):

- Work on a branch and open a pull request. Never push to `main` on GitHub: the next mirror
  update discards anything pushed there.
- A pull request is copied to a GitLab merge request automatically, and the maintainer merges
  it on GitLab. Don't merge pull requests on GitHub.
- Merges are fast-forward only, so before asking for a merge make sure the branch contains the
  latest `main` (merge `main` in, or rebase and push the branch again).
- Issues and their comments sync both ways. Branches other than `main`, and merge requests
  opened on GitLab, exist only on GitLab, so they can't be seen from GitHub.

If your `origin` is GitLab (the maintainer's machine): push branches and `main` to `origin` as
usual. GitHub follows within about a minute.
