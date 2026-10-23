# Contributing

Thanks for helping improve Awesome Harness Engineering.

## What belongs here

Please submit resources that are directly useful for designing, evaluating, or
operating agent harnesses. Good additions usually focus on one or more of:

- Context engineering and working-state management
- Tool design, tool calling, and environment control
- Evals, grading, benchmarking, or observability
- Long-running agents, resumability, retries, or orchestration
- Repo-local instructions such as `AGENTS.md`, specs, or workflow scaffolding
- Reference implementations that make harness design inspectable

Generic AI news, model launch posts, or broad agent-framework marketing pages
usually do not belong unless they contain concrete harness-level guidance.

## Quality bar

When proposing a new entry, prefer resources that are:

- Primary sources or original technical write-ups
- Non-duplicative with an existing entry
- Still available and reachable
- Specific enough that the description can explain why the resource matters

## Self-submissions and commercial promotion

Independent developers may submit an open-source project or original technical
write-up that they personally create or maintain. Companies and their
representatives may also submit a genuinely open-source project when the entry
links directly to its public source repository and meets the same technical
quality bar. Disclose the relationship in the pull request so reviewers can
evaluate the entry fairly.

We do not accept company product homepages, sales or lead-generation pages,
closed-source product promotion, referral links, campaign parameters, badges,
or promotional claims. A public source repository should make the relevant
harness design inspectable and clearly state its license.

## Entry format

Please follow this format:

```md
- [Name](https://example.com) - Short description focused on why this matters for harness engineering.
```

Keep descriptions concise and practical. Explain the harness angle, not just the
topic.

## Placement

- Put the entry in the most specific existing section or subsection that fits.
- If a new subsection is genuinely needed, keep its title short and broad
  enough to support future additions.
- Avoid adding the same resource to multiple sections.

## Before opening a PR

- Confirm the link works.
- Confirm the resource is actually about harness-relevant concerns.
- Confirm the description is accurate and not promotional.
- Check for duplicates in the README.
- Keep the diff focused.
- Disclose whether you create, maintain, work for, or are otherwise affiliated
  with the submitted resource.
- For a company-maintained project, link directly to the public source
  repository rather than a product or marketing page.

## Pull requests

Small, focused pull requests are easiest to review.

If you are adding several links at once, include a short note explaining the
theme that connects them and why they belong in the chosen section.
