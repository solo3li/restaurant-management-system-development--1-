## 2026-10-23T20:35:46Z
You are challenger_2, an adversarial testing challenger.
Your working directory is: /root/motaem/.agents/teamwork/challenger_2
Parent orchestrator directory is: /root/motaem/.agents/teamwork/orchestrator_1

Read:
- /root/motaem/.agents/teamwork/ORIGINAL_REQUEST.md
- /root/motaem/PROJECT.md
- /root/motaem/AGENTS.md
- /root/motaem/.agents/teamwork/worker_1/handoff.md
- /root/motaem/TEST_READY.md

Mission:
Adversarially challenge data integrity, state transitions, and concurrency on Restaurant Profile:
1. Write a standalone test script or challenge harness in your working directory to probe:
   - Rapid sequential or concurrent updates (e.g. updating color while uploading logo).
   - Partial updates (e.g. updating only phone without clearing name/bio/logo/cover).
   - Whitespace stripping and normalization of phone/email/address.
   - Boundary checks for brand_color (case insensitivity `#ffffff` vs `#FFFFFF`, invalid hex lengths `#123`, `#1234567`).
   - Media cleanup or overwriting behavior.
2. Execute your challenge harness against the Django test environment.
3. Conclude with an explicit verdict: APPROVE or REQUEST_CHANGES.
4. Write handoff report to /root/motaem/.agents/teamwork/challenger_2/handoff.md and notify parent.
