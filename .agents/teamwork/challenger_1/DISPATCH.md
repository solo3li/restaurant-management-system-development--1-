## 2026-10-23T20:35:46Z
You are challenger_1, an adversarial testing challenger.
Your working directory is: /root/motaem/.agents/teamwork/challenger_1
Parent orchestrator directory is: /root/motaem/.agents/teamwork/orchestrator_1

Read:
- /root/motaem/.agents/teamwork/ORIGINAL_REQUEST.md
- /root/motaem/PROJECT.md
- /root/motaem/AGENTS.md
- /root/motaem/.agents/teamwork/worker_1/handoff.md
- /root/motaem/TEST_READY.md

Mission:
Adversarially challenge the Restaurant Profile implementation:
1. Write a standalone test script or stress harness in your working directory to probe:
   - Bypassing RBAC checks (e.g. branch cashier trying to POST to /restaurant/profile/ or /api/restaurant/profile/).
   - Cross-tenant tampering (e.g. user from tenant A trying to mutate tenant B data by passing tenant_id parameter or header).
   - Injection of malicious payloads, SQL injection strings, XSS payloads in name/bio/address, extremely long strings, null bytes.
   - Edge case media uploads: 0-byte files, corrupt image headers, fake MIME types, dotfile extensions.
2. Execute your challenge tests and inspect results.
3. Conclude with an explicit verdict: APPROVE (if system robustly withstands all adversarial attacks) or REQUEST_CHANGES (if security or stability flaw exposed).
4. Write handoff report to /root/motaem/.agents/teamwork/challenger_1/handoff.md and notify parent.
