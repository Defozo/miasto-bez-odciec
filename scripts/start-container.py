"""Container entrypoint; secrets stay in process environment, never CLI arguments."""
import os
import sys
from urllib.parse import quote

if os.getenv('SMART_CITY_DB_PASSWORD') and not os.getenv('DATABASE_URL'):
    os.environ['DATABASE_URL'] = 'postgresql+psycopg://smartcity:' + quote(os.environ['SMART_CITY_DB_PASSWORD'], safe='') + '@db:5432/smartcity'

command = sys.argv[1] if len(sys.argv) > 1 else 'api'
if command == 'init':
    from alembic.config import Config
    from alembic import command as migration
    migration.upgrade(Config('alembic.ini'), 'head')
    from services.api.init_db import initialize
    initialize(seed=True)
elif command == 'worker':
    sys.argv = [sys.argv[0]]
    from services.worker.main import main
    main()
else:
    import uvicorn
    uvicorn.run('services.api.main:app', host='0.0.0.0', port=8000, proxy_headers=False)
