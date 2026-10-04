"""Create only missing project secrets in psst; never print secret values."""
import json
import secrets
import shutil
import subprocess

exe = shutil.which('psst')
if not exe:
    raise SystemExit('Install psst before configuring secrets.')
response = subprocess.run([exe, '--global', 'list', '--json'], capture_output=True, text=True, check=True)
existing = {entry['name'] for entry in json.loads(response.stdout)['secrets']}
for name in ('SMART_CITY_DB_PASSWORD', 'SMART_CITY_APP_SECRET', 'SMART_CITY_OPERATOR_PASSWORD', 'SMART_CITY_VERIFIER_PASSWORD', 'SMART_CITY_ADMIN_PASSWORD'):
    if name not in existing:
        subprocess.run([exe, '--global', 'set', name, '--stdin', '--tag', 'smart-city'], input=secrets.token_urlsafe(36), text=True, capture_output=True, check=True)
        print(f'{name}: created in psst')
    else:
        print(f'{name}: already present')
