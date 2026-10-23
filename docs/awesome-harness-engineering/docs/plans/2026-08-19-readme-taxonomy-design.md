# README Taxonomy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use the writing plan below task-by-task.

**Goal:** Make the catalog easier to scan by dividing broad resource lists into precise, stable subcategories without adding, removing, or duplicating resources.

**Architecture:** Keep the existing top-level sections and anchors for backward compatibility. Add level-three headings inside the five broad sections, move each resource into exactly one best-fit category, and expose the new hierarchy through a nested table of contents.

**Tech Stack:** Markdown, Git, ripgrep, awk, and the existing GitHub Actions link checker.

---

### Task 1: Establish invariants

**Files:**
- Inspect: `README.md`

1. Count resource entries by current top-level section.
2. Record the complete URL multiset from `HEAD:README.md`.
3. Treat unchanged resource count, unchanged URL multiset, and unique placement as required invariants.

### Task 2: Add the taxonomy

**Files:**
- Modify: `README.md`

1. Divide Context into context delivery and durable memory/knowledge.
2. Divide Constraints into tool boundaries, security/authorization, and operational autonomy.
3. Divide Specs into instruction formats, spec-driven workflows, and operating principles.
4. Divide Evals into evaluation methods, verification/quality gates, and telemetry/observability.
5. Divide Benchmarks into coding/terminal, web/computer use, tool/MCP, multi-agent/general, and safety/economic domains.
6. Divide Runtimes into runtime foundations, sandbox/execution infrastructure, coding harnesses, multi-agent orchestration, browser/tool integration, and workflow/profile assets.
7. Keep each resource in one primary category and avoid adding duplicate links.

### Task 3: Update navigation

**Files:**
- Modify: `README.md`

1. Add nested table-of-contents links for all new level-three headings.
2. Verify every generated anchor matches GitHub Markdown anchor rules.

### Task 4: Verify and publish

**Files:**
- Verify: `README.md`

1. Run `git diff --check`; expect no output.
2. Compare the URL multiset in `HEAD:README.md` with the working file; expect no differences except table-of-contents anchors.
3. Count catalog resources; expect 141 before and after.
4. Check duplicate external URLs; expect no new duplicates.
5. Commit and push the taxonomy change.
6. Confirm the repository link-check workflow completes successfully.
