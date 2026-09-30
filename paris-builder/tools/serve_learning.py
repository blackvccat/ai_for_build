"""Run the persistent local learning app: python tools/serve_learning.py."""
import sys
import argparse
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from paris_builder.learning import DB, build_database

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    os.environ['PARIS_PORT'] = str(args.port)
    if not DB.exists():
        print('Building learning database...', flush=True)
        build_database()
    import uvicorn
    uvicorn.run('paris_builder.learning_web:app', host='127.0.0.1', port=args.port, log_level='warning')
