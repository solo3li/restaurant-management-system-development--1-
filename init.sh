#!/bin/bash
set -e

echo "=== Harness Initialization ==="

echo "=== venv/bin/python manage.py check ==="
venv/bin/python manage.py check

echo "=== venv/bin/python test_system.py ==="
venv/bin/python test_system.py

echo "=== venv/bin/python test_e2e_rbac.py ==="
venv/bin/python test_e2e_rbac.py

echo "=== venv/bin/python test_landing_and_profile.py ==="
venv/bin/python test_landing_and_profile.py

echo "=== venv/bin/python test_multilingual_5lang.py ==="
venv/bin/python test_multilingual_5lang.py

echo "=== venv/bin/python manage.py test test_landing_persona_sync ==="
venv/bin/python manage.py test test_landing_persona_sync

echo "=== venv/bin/python manage.py test test_landing_voice_leads ==="
venv/bin/python manage.py test test_landing_voice_leads

echo "=== venv/bin/python manage.py test test_landing_assistant_admin_tabs ==="
venv/bin/python manage.py test test_landing_assistant_admin_tabs

echo "=== venv/bin/python manage.py test test_landing_voice_customization ==="
venv/bin/python manage.py test test_landing_voice_customization

echo "=== Verification Complete ==="
echo ""
echo "Next steps:"
echo "1. Read feature_list.json to see current feature state"
echo "2. Pick ONE unfinished feature to work on"
echo "3. Implement only that feature"
echo "4. Re-run verification before claiming done"
