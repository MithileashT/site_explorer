# Git Branch-Aware Site Data Loading — Implementation Plan

> **Feature:** Ensure the correct `sootballs_sites` git branch is used when serving site data.
> **Status:** Ready for implementation

---

## Background

The `sootballs_sites` repo has per-site branches whose names match the site ID exactly (e.g. `mncyok001`, `alcbrk001`). About 39 of the 100+ sites have their own branch; the rest use `main`. The current `SiteMapService` reads directly from whichever branch happens to be checked out on disk — which is wrong.

**Key constraint:** `git checkout` changes the entire working tree, affecting all sites simultaneously. We must use `git show <branch>:path` to read file content from a specific branch without touching the working directory.

---

## File Map

| File | Action |
|---|---|
| `backend/core/config.py` | Add `sootballs_repo_root` setting |
| `backend/services/sitemap/git_manager.py` | **NEW** — `GitRepoManager` class |
| `backend/services/sitemap/service.py` | Add git-aware read layer |
| `backend/app/routes/sitemap.py` | Add 4 branch endpoints + wire manager |
| `frontend/lib/types.ts` | Add `BranchInfo` type |
| `frontend/lib/api.ts` | Add 4 branch API functions |
| `frontend/app/sitemap/page.tsx` | Branch badge, override dropdown, sync button |

---

## Task Breakdown

### Task 1 — Config: add `sootballs_repo_root`

**File:** `backend/core/config.py`

Add one new setting after `sootballs_sites_root`:

```python
# ── Site Map (sootballs_sites repo) ──────────────────────────────────────────
sootballs_sites_root: str = os.getenv(
    "SOOTBALLS_SITES_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "sootballs_sites", "sites"),
)
sootballs_repo_root: str = os.getenv(
    "SOOTBALLS_REPO_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "sootballs_sites"),
)
```

`sootballs_repo_root` points to the git repo root (parent of `sites/`). This is the `cwd` for all `git` subprocess calls.

---

### Task 2 — New service: `GitRepoManager`

**File:** `backend/services/sitemap/git_manager.py` *(create new)*

```python
"""
services/sitemap/git_manager.py
────────────────────────────────
GitRepoManager — branch-aware, no-checkout git file reader for sootballs_sites.

All reads use `git show <ref>:sites/<site_id>/<rel_path>` so the working tree
is never touched. Branch list is fetched from remote and cached for 5 minutes.
"""
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Set

from core.logging import get_logger

logger = get_logger(__name__)

# Site-ID branch name pattern (e.g. mncyok001, alcbrk001)
_SITE_BRANCH_RE = re.compile(r"^[a-z]{3}[a-z0-9]{3}[0-9]{3}$")
_CACHE_TTL = 300  # seconds


class GitRepoManager:
    """
    Read-only, branch-aware access to sootballs_sites without git checkout.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = Path(repo_root).resolve()
        # branch override: site_id → explicit ref e.g. "origin/mncyok001"
        self._overrides: Dict[str, str] = {}
        # cached set of remote site-ID branches (short names)
        self._site_branches: Optional[Set[str]] = None
        self._cache_ts: float = 0.0
        self._last_fetch_ts: float = 0.0
        logger.info("GitRepoManager: repo_root=%s", self.repo_root)

    # ── Git subprocess ─────────────────────────────────────────────────────────

    def _git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_root),
            capture_output=True,
            check=check,
        )

    # ── Remote sync ───────────────────────────────────────────────────────────

    def fetch(self, force: bool = False) -> None:
        """Run `git fetch origin --prune`. Throttled to once per 5 minutes."""
        now = time.monotonic()
        if not force and (now - self._last_fetch_ts) < _CACHE_TTL:
            return
        logger.info("GitRepoManager: fetching origin…")
        result = self._git("fetch", "origin", "--prune")
        if result.returncode != 0:
            logger.warning("git fetch failed: %s", result.stderr.decode())
        else:
            self._last_fetch_ts = now
            # Invalidate branch cache so next list_site_branches() re-reads
            self._site_branches = None
            self._cache_ts = 0.0

    # ── Branch discovery ──────────────────────────────────────────────────────

    def list_site_branches(self) -> Set[str]:
        """
        Return the set of short branch names that match the site-ID pattern
        and exist as remote tracking refs (origin/<name>).
        Result is cached for 5 minutes.
        """
        now = time.monotonic()
        if self._site_branches is not None and (now - self._cache_ts) < _CACHE_TTL:
            return self._site_branches

        result = self._git("branch", "-r")
        branches: Set[str] = set()
        for line in result.stdout.decode().splitlines():
            name = line.strip().replace("origin/", "")
            if _SITE_BRANCH_RE.match(name):
                branches.add(name)

        self._site_branches = branches
        self._cache_ts = now
        logger.debug("GitRepoManager: found %d site branches", len(branches))
        return branches

    def list_all_remote_branches(self) -> list[str]:
        """Return all remote-tracking short branch names (for override dropdown)."""
        result = self._git("branch", "-r")
        names = []
        for line in result.stdout.decode().splitlines():
            name = line.strip()
            if "->" in name:  # skip HEAD pointer
                continue
            short = name.replace("origin/", "")
            names.append(short)
        return sorted(names)

    def resolve_branch(self, site_id: str) -> str:
        """
        Return the git ref to use for the given site, as a fully-qualified
        remote ref (e.g. "origin/mncyok001" or "origin/main").

        Priority:
          1. Manual override set via set_override()
          2. Site-specific remote branch (origin/<site_id>) if it exists
          3. origin/main
        """
        if site_id in self._overrides:
            return self._overrides[site_id]
        site_branches = self.list_site_branches()
        if site_id in site_branches:
            return f"origin/{site_id}"
        return "origin/main"

    def set_override(self, site_id: str, branch: str) -> None:
        """Override which branch to use for a specific site."""
        self._overrides[site_id] = f"origin/{branch}" if not branch.startswith("origin/") else branch
        logger.info("GitRepoManager: override %s → %s", site_id, self._overrides[site_id])

    def clear_override(self, site_id: str) -> None:
        """Remove branch override for a site (reverts to auto-detect)."""
        self._overrides.pop(site_id, None)

    # ── File reading ──────────────────────────────────────────────────────────

    def read_file(self, branch: str, site_id: str, rel_path: str) -> Optional[bytes]:
        """
        Read a file from a specific git ref without touching the working tree.
        Uses: git show <branch>:sites/<site_id>/<rel_path>
        Returns raw bytes on success, None if the path does not exist on that branch.
        """
        git_path = f"sites/{site_id}/{rel_path}"
        result = self._git("show", f"{branch}:{git_path}")
        if result.returncode == 0:
            return result.stdout
        return None

    def read_file_for_site(self, site_id: str, rel_path: str) -> Optional[bytes]:
        """Convenience: resolve branch automatically then read the file."""
        branch = self.resolve_branch(site_id)
        return self.read_file(branch, site_id, rel_path)

    # ── Commit metadata ───────────────────────────────────────────────────────

    def get_last_commit(self, branch: str) -> dict:
        """Return hash, subject, and ISO date of the tip of a branch."""
        result = self._git(
            "log", "-1",
            "--pretty=format:%H|%s|%aI",
            branch,
        )
        if result.returncode != 0:
            return {"hash": "", "message": "", "date": ""}
        parts = result.stdout.decode("utf-8", errors="replace").split("|", 2)
        return {
            "hash":    parts[0] if len(parts) > 0 else "",
            "message": parts[1] if len(parts) > 1 else "",
            "date":    parts[2] if len(parts) > 2 else "",
        }
```

---

### Task 3 — Modify `SiteMapService` for git-aware reads

**File:** `backend/services/sitemap/service.py`

#### 3a. Constructor changes

```python
from services.sitemap.git_manager import GitRepoManager   # new import

class SiteMapService:
    def __init__(self, sites_root: str, git_manager: Optional["GitRepoManager"] = None) -> None:
        self.root = Path(sites_root).resolve()
        self._git = git_manager          # may be None (filesystem-only mode)
        logger.info("SiteMapService: root=%s, git=%s", self.root, "enabled" if git_manager else "disabled")
```

#### 3b. New private read helper

Add `_read_bytes(site_id, *rel_paths)` alongside `_find()`:

```python
def _read_bytes(self, site_id: str, *relative_paths: str) -> Optional[bytes]:
    """
    Read the first matching file, preferring git branch reads when a
    GitRepoManager is configured, falling back to the filesystem.
    """
    if self._git is not None:
        for rp in relative_paths:
            data = self._git.read_file_for_site(site_id, rp)
            if data is not None:
                return data
        return None
    # Filesystem fallback
    p = self._find(site_id, *relative_paths)
    return p.read_bytes() if p else None
```

#### 3c. Refactor each method to use `_read_bytes`

Replace `_find()` + `open()` / `cv2.imread()` calls with `_read_bytes()` + in-memory decoders:

| Method | Old pattern | New pattern |
|---|---|---|
| `get_map_meta` | `open(yaml_path)` + `cv2.imread(img_path)` for size | `_read_bytes(...yaml)` → `yaml.safe_load(io.BytesIO(data))` · `_read_bytes(...png)` → `cv2.imdecode(np.frombuffer(data), GRAYSCALE)` |
| `get_map_image` | `cv2.imread(str(img_path))` | `cv2.imdecode(np.frombuffer(data, np.uint8), GRAYSCALE)` |
| `get_site_data` (spots) | `open(spots_path)` | `io.StringIO(data.decode('utf-8'))` |
| `get_site_data` (racks) | `open(racks_path)` | `io.StringIO(data.decode('utf-8'))` |
| `get_site_data` (regions) | `open(regions_path)` | `io.StringIO(data.decode('utf-8'))` |
| `get_site_data` (robots) | `open(robots_path)` | `json.loads(data.decode('utf-8'))` |
| `get_nav_graph` | `svg_path.read_text()` | `_read_bytes(...svg).decode('utf-8')` |

`_find()` stays unchanged for the filesystem fallback path.

Required new imports: `import io`, `import numpy as np` (already dependency).

#### 3d. `list_sites()` in git mode

When `_git` is available, sites come from `git ls-tree --name-only origin/main sites/` rather than filesystem scan:

```python
def list_sites(self) -> List[Dict[str, str]]:
    if self._git is not None:
        result = self._git._git("ls-tree", "--name-only", "origin/main", "sites/")
        if result.returncode == 0:
            names = [n for n in result.stdout.decode().splitlines() if n.strip()]
            return [{"id": n, "name": n} for n in sorted(names)]
    # filesystem fallback (existing code)
    ...
```

---

### Task 4 — New routes in `sitemap.py`

**File:** `backend/app/routes/sitemap.py`

#### 4a. Wire `GitRepoManager` into singleton

```python
from services.sitemap.git_manager import GitRepoManager
from core.config import settings

_svc: Optional[SiteMapService] = None
_git_mgr: Optional[GitRepoManager] = None

def _get_git() -> GitRepoManager:
    global _git_mgr
    if _git_mgr is None:
        _git_mgr = GitRepoManager(settings.sootballs_repo_root)
    return _git_mgr

def _get_svc() -> SiteMapService:
    global _svc
    if _svc is None:
        _svc = SiteMapService(settings.sootballs_sites_root, _get_git())
    return _svc
```

#### 4b. New endpoints (add **before** `{site_id}/map` route to avoid path conflicts)

```
GET  /api/v1/sitemap/branches                → list all remote branches (for override dropdown)
GET  /api/v1/sitemap/{site_id}/branch        → BranchInfo response
POST /api/v1/sitemap/{site_id}/branch        → body: {"branch": "mncyok001"} — set override
DELETE /api/v1/sitemap/{site_id}/branch      → clear override
POST /api/v1/sitemap/sync                    → git fetch, clears branch cache
```

**Response schema for `GET /{site_id}/branch`:**
```json
{
  "branch": "mncyok001",
  "ref": "origin/mncyok001",
  "is_site_specific": true,
  "is_override": false,
  "last_commit": {
    "hash": "abc1234",
    "message": "Update spots.csv",
    "date": "2025-01-15T10:30:00+09:00"
  },
  "available_branches": ["main", "mncyok001", "alcbrk001", "..."]
}
```

**Route registration order matters** — FastAPI matches in declaration order. Register static-path routes (`/branches`, `/sync`) **before** parameterised routes (`/{site_id}/...`) to prevent `branches` from being captured as a `site_id`.

#### 4c. Pydantic request model

```python
from pydantic import BaseModel

class BranchOverrideRequest(BaseModel):
    branch: str
```

---

### Task 5 — Frontend types

**File:** `frontend/lib/types.ts`

Add after the `NavGraph` block:

```typescript
// ──────────────────────────────────────────────
// Git Branch Info
// ──────────────────────────────────────────────
export interface CommitInfo {
  hash: string;
  message: string;
  date: string;
}

export interface BranchInfo {
  branch: string;           // short name, e.g. "mncyok001" or "main"
  ref: string;              // full ref, e.g. "origin/mncyok001"
  is_site_specific: boolean;
  is_override: boolean;
  last_commit: CommitInfo | null;
  available_branches: string[];
}
```

---

### Task 6 — Frontend API functions

**File:** `frontend/lib/api.ts`

Add a new section after the Sitemap block:

```typescript
// ── Sitemap — Git Branch ──────────────────────────────────────────────────

export async function getSiteBranchInfo(siteId: string): Promise<BranchInfo> {
  const { data } = await http.get<BranchInfo>(`/sitemap/${siteId}/branch`);
  return data;
}

export async function setSiteBranch(siteId: string, branch: string): Promise<void> {
  await http.post(`/sitemap/${siteId}/branch`, { branch });
}

export async function clearSiteBranch(siteId: string): Promise<void> {
  await http.delete(`/sitemap/${siteId}/branch`);
}

export async function syncSiteRepo(): Promise<{ branches_found: number }> {
  const { data } = await http.post<{ branches_found: number }>("/sitemap/sync");
  return data;
}
```

Import `BranchInfo` in the type import block at the top of `api.ts`.

---

### Task 7 — Frontend UI

**File:** `frontend/app/sitemap/page.tsx`

#### 7a. New state variables

```typescript
const [branchInfo,  setBranchInfo]  = useState<BranchInfo | null>(null);
const [showBranchDropdown, setShowBranchDropdown] = useState(false);
const [syncing, setSyncing] = useState(false);
```

#### 7b. Load branch info when site changes

In the `loadSite` callback, after the existing `Promise.all`, add:

```typescript
// load branch info (non-blocking, best-effort)
getSiteBranchInfo(id).then(setBranchInfo).catch(() => setBranchInfo(null));
```

#### 7c. Branch badge component (inline JSX in header bar)

Place next to the site selector:

```tsx
{/* Branch badge */}
{branchInfo && (
  <div className="relative">
    <button
      onClick={() => setShowBranchDropdown(v => !v)}
      className={clsx(
        "flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono",
        branchInfo.is_site_specific
          ? "bg-green-900/40 text-green-300 border border-green-700/50"
          : "bg-slate-700/60 text-slate-400 border border-slate-600/50"
      )}
    >
      <GitBranch size={11} />
      {branchInfo.branch}
      {branchInfo.is_override && <span className="text-orange-400 ml-1">*</span>}
      <ChevronDown size={11} />
    </button>

    {/* Override dropdown */}
    {showBranchDropdown && (
      <div className="absolute top-full mt-1 left-0 z-50 bg-slate-800 border border-slate-600 rounded shadow-xl min-w-48 py-1">
        <div className="px-3 py-1.5 text-[10px] text-slate-500 uppercase tracking-wider">
          Switch branch
        </div>
        {branchInfo.available_branches.map(b => (
          <button
            key={b}
            onClick={async () => {
              setShowBranchDropdown(false);
              await setSiteBranch(siteId, b);
              const info = await getSiteBranchInfo(siteId);
              setBranchInfo(info);
              loadSite(siteId);   // reload canvas data from new branch
            }}
            className={clsx(
              "w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-slate-700",
              b === branchInfo.branch ? "text-green-300" : "text-slate-300"
            )}
          >
            {b} {b === branchInfo.branch && "✓"}
          </button>
        ))}
        {branchInfo.is_override && (
          <>
            <div className="border-t border-slate-700 my-1" />
            <button
              onClick={async () => {
                setShowBranchDropdown(false);
                await clearSiteBranch(siteId);
                const info = await getSiteBranchInfo(siteId);
                setBranchInfo(info);
                loadSite(siteId);
              }}
              className="w-full text-left px-3 py-1.5 text-xs text-orange-400 hover:bg-slate-700"
            >
              ↩ Reset to auto-detect
            </button>
          </>
        )}
      </div>
    )}
  </div>
)}
```

#### 7d. Sync button (header bar, next to branch badge)

```tsx
<button
  onClick={async () => {
    setSyncing(true);
    try {
      await syncSiteRepo();
      // Refresh branch info and site data with latest remote
      const info = await getSiteBranchInfo(siteId);
      setBranchInfo(info);
      loadSite(siteId);
    } finally {
      setSyncing(false);
    }
  }}
  disabled={syncing}
  title="Sync sootballs_sites from remote"
  className="p-1.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
>
  <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
</button>
```

`RefreshCw` is already imported. Add `GitBranch` to the lucide imports.

#### 7e. Commit info tooltip (optional enhancement)

When `branchInfo.last_commit` is available, show hash + message as a `title` attribute on the badge, or as a small line below.

---

## Execution Order

```
Task 1  config.py          → add sootballs_repo_root (30s, no deps)
Task 2  git_manager.py     → create new file (~3 min)
Task 3  service.py         → refactor to use _read_bytes (~5 min)
Task 4  sitemap.py routes  → add 4 new endpoints (~3 min)
Task 5  lib/types.ts       → add BranchInfo types (1 min)
Task 6  lib/api.ts         → add 4 API functions (1 min)
Task 7  sitemap page.tsx   → branch badge + dropdown + sync button (~5 min)
```

Tasks 1–2 must complete before Tasks 3–4. Tasks 5–7 are frontend-only and can proceed after Task 4 defines the API contract.

---

## Edge Cases & Notes

| Scenario | Behaviour |
|---|---|
| Site has no dedicated branch | `resolve_branch` returns `origin/main` — `is_site_specific: false` |
| File doesn't exist on target branch | `read_file` returns `None` → service method returns empty/default (same as current filesystem miss) |
| `git fetch` fails (no network) | `fetch()` logs warning, continues using stale cache — no crash |
| Override set to branch that doesn't have the file | Falls back gracefully (same as above) |
| `sootballs_repo_root` is not a git repo | `_git()` calls return non-zero returncode → service falls through to filesystem |
| First request after startup | No `fetch()` on startup — branch cache is empty, `list_site_branches()` reads remote refs that are already fetched (existing local clone) |

---

## Not In Scope

- Automatic fetch on site selection (too slow — user triggers via Sync button)
- Per-file branch granularity (all files for a site always use the same branch)
- Writing/committing back to the repo
- Branch creation or deletion
