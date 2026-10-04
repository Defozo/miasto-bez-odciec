"""A project-specific entry point for recoverable detached development processes."""
import os
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
role = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
sys.argv = [sys.argv[0]]
if role == 'api':
    import uvicorn
    uvicorn.run('services.api.main:app', host='127.0.0.1', port=port, proxy_headers=False)
elif role == 'worker':
    from services.worker.main import main
    main()
else:
    raise SystemExit('Expected api or worker')
