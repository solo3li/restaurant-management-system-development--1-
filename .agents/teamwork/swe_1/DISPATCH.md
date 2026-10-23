## 2026-10-23T21:25:55Z

[Message] timestamp=2026-10-23T21:25:55Z sender=7de6caf7-803c-4d00-92b5-fda832f1fe27 priority=MESSAGE_PRIORITY_HIGH content=You are the SWE Light Orchestrator for this task.

Working directory: /root/motaem/.agents/teamwork/swe_1
Original request file: /root/motaem/.agents/teamwork/ORIGINAL_REQUEST.md

Please review the user request timestamped 2026-10-23T21:24:43Z:
A single self-contained set of improvements (Small focused team / مطور رئيسي مع مراجع صارم):
1. R1. Landing Page Navbar Simplification & Auth States:
   - Remove content anchor tabs (المميزات, الكاشير والمطبخ, كول سنتر AI, باقات الاشتراك, الأسئلة الشائعة) from desktop navbar and mobile drawer while keeping all page sections visible.
   - Guest visitors: Language Switcher (عربي / EN), "تسجيل الدخول / Sign In", and "ابدأ مجاناً / Start Free" CTA button.
   - Authenticated users (Restaurant Owners / Managers): Hide Sign In / Start Free buttons and display "لوحة الإدارة / Dashboard" linking to /dashboard/, "البروفايل / Profile" linking to user/subscription profile page, and Language Switcher (عربي / EN).
2. R2. 100% Bilingual Landing Page:
   - Full Arabic & Full English coverage across templates/landing.html (badges, headers, stats, feature cards, FAQ).
   - Dynamic switching RTL/LTR without reload issues.
3. R3. Comprehensive User & Subscription Profile Page:
   - Dedicated profile page at /user/profile/ or /profile/ with account/restaurant overview, active plan card, usage limits with visual progress bars (branches & staff), plan upgrade modal, and primary CTA to /dashboard/.
4. R4. Post-Registration Routing:
   - Redirect to profile page upon successful registration on /register/.
   - Security: non-authenticated users redirected to login.

Verification:
- Verification script: ./init.sh
- Tests: test_system.py, test_e2e_rbac.py, test_restaurant_profile.py, venv/bin/python manage.py check

Follow the SWE Light loop: dispatch implementer, adversarial review rounds, verify tests pass. Keep your progress.md and BRIEFING.md updated in /root/motaem/.agents/teamwork/swe_1.
Report completion back when all acceptance criteria are met and verification passes.
