#!/usr/bin/env python3
# Sets `entryCreator` and `entryContributor` fields on JSON entries based on git history.
#
# - The creator (first commit author) is written to `entryCreator` (dcterms:creator)
# - All subsequent contributors are written to `entryContributor` (dcterms:contributor)
# - Both fields hold foaf:Agent objects: {"@type": "foaf:Person", "name": "@handle"}
# - Existing entries are never duplicated (idempotent)
#
# For files just renamed by inject_uuids.py (not yet committed under their new name),
# git history is retried against the original pre-UUID filename as a fallback.
#
# Requires git to be available in PATH and the script to run inside the repository.

import json
import re
import subprocess
import sys
from pathlib import Path

DIRS = ["terms", "references", "properties"]

# Matches the trailing 16-char hex UUID suffix added by inject_uuids.py
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


def git_log_authors(file_path: Path) -> list[str]:
    """Return git log author lines for a given path, newest first."""
    cmd = ["git", "log", "--format=%an", "--follow", "--", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip().splitlines()


def git_handles(file_path: Path) -> list[str]:
    """
    Return all GitHub handles who committed the file, creator (oldest) first.
    Falls back to the pre-UUID filename if the current path has no history yet.
    """
    lines = git_log_authors(file_path)

    # Fallback: strip UUID suffix and retry with the original filename
    if not lines:
        match = UUID_SUFFIX_RE.search(file_path.stem)
        if match:
            original = file_path.with_name(
                UUID_SUFFIX_RE.sub("", file_path.stem) + ".json"
            )
            lines = git_log_authors(original)

    if not lines:
        return []

    def to_handle(name: str) -> str:
        return "@" + name.strip().lower().replace(" ", "-")

    all_authors = [to_handle(line) for line in lines if line.strip()]

    # Creator is the last entry (oldest commit), move to front then deduplicate
    creator = all_authors[-1]
    rest = [a for a in all_authors[:-1] if a != creator]

    seen: set[str] = set()
    ordered: list[str] = []
    for handle in [creator] + rest:
        if handle not in seen:
            seen.add(handle)
            ordered.append(handle)

    return ordered


def make_agent(handle: str) -> dict:
    """Build a foaf:Agent object from a GitHub handle."""
    return {"@type": "foaf:Person", "name": handle}


def agent_names(agents: list[dict] | dict | None) -> set[str]:
    """Extract the set of name values from an agentOrList field."""
    if not agents:
        return set()
    if isinstance(agents, dict):
        return {agents.get("name", "")}
    return {a.get("name", "") for a in agents if isinstance(a, dict)}


def main() -> int:
    updated_count = 0

    for dir_name in DIRS:
        data_dir = Path(dir_name)
        if not data_dir.exists():
            continue

        for file_path in sorted(data_dir.glob("*.json")):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue  # let validate_glossary.py report parse errors

            handles = git_handles(file_path)
            if not handles:
                continue  # untracked file, skip

            creator_handle = handles[0]
            contributor_handles = handles[1:]

            changed = False

            # --- entryCreator (dcterms:creator) ---
            existing_creator = data.get("entryCreator")
            existing_creator_names = agent_names(
                [existing_creator] if isinstance(existing_creator, dict) else existing_creator
            )
            if creator_handle not in existing_creator_names:
                data["entryCreator"] = make_agent(creator_handle)
                print(f"  set entryCreator '{creator_handle}' on {dir_name}/{file_path.name}")
                changed = True

            # --- entryContributor (dcterms:contributor) ---
            existing_contributors = data.get("entryContributor", [])
            # Normalise to list for uniform handling
            if isinstance(existing_contributors, dict):
                existing_contributors = [existing_contributors]
            existing_contributor_names = agent_names(existing_contributors)

            new_agents = [
                make_agent(h)
                for h in contributor_handles
                if h not in existing_contributor_names
            ]
            if new_agents:
                data["entryContributor"] = existing_contributors + new_agents
                for agent in new_agents:
                    print(f"  added entryContributor '{agent['name']}' to {dir_name}/{file_path.name}")
                changed = True

            if not changed:
                continue

            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated_count += 1

    print(f"\nDone — {updated_count} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
