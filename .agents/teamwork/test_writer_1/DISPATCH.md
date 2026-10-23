## 2026-10-23T20:20:25Z
You are test_writer_1, an E2E test engineer.
Your working directory is: /root/motaem/.agents/teamwork/test_writer_1
Parent orchestrator directory is: /root/motaem/.agents/teamwork/orchestrator_1

Read:
- /root/motaem/.agents/teamwork/ORIGINAL_REQUEST.md
- /root/motaem/PROJECT.md
- /root/motaem/AGENTS.md
- /root/motaem/.agents/teamwork/explorer_survey_1/handoff.md
- /root/motaem/.agents/teamwork/explorer_survey_2/handoff.md
- /root/motaem/.agents/teamwork/explorer_survey_3/handoff.md

Write ownership:
- You EXCLUSIVELY own:
  /root/motaem/TEST_INFRA.md
  /root/motaem/test_restaurant_profile.py
  /root/motaem/TEST_READY.md
- DO NOT edit production code or templates.

Mission:
1. Create /root/motaem/TEST_INFRA.md based on the template in PROJECT.md and the 4-tier methodology.
2. Implement an opaque-box test suite in /root/motaem/test_restaurant_profile.py (runnable via `venv/bin/python test_restaurant_profile.py` using Django test environment or RequestFactory/Client like test_e2e_rbac.py):
   - Tier 1: Feature Coverage (>=5 test cases per feature: GET /restaurant/profile/, POST name & bio, POST phone, email, address, POST brand_color, POST logo_image and cover_image uploads).
   - Tier 2: Boundary & Corner Cases (empty name rejected, max length bio, invalid email format rejected, invalid hex color rejected, oversized logo >2MB rejected, oversized cover >5MB rejected, disallowed extensions rejected).
   - Tier 3: Cross-Feature & Security Combinations (Strict RBAC: Owner HTTP 200, HQ Manager HTTP 200, Cashier HTTP 403, Kitchen HTTP 403, Driver HTTP 403, unauthenticated HTTP 302 redirect; Multi-Tenant Isolation: Tenant A user cannot see or alter Tenant B restaurant profile).
   - Tier 4: Real-World Scenarios (Complete update flow verifying persistent reflection in DB and subsequent GET).
3. Verify test runner execution and document counts per tier.
4. When test suite is ready and documented, create /root/motaem/TEST_READY.md.
5. Write your handoff report to /root/motaem/.agents/teamwork/test_writer_1/handoff.md and notify parent.
