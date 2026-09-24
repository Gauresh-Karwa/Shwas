import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ingestion.pipeline import run_ingestion_cycle

def main():
    print('Running ingestion cycle against live CPCB API...')
    summary = run_ingestion_cycle()
    print('\nSummary:')
    for key, value in summary.items():
        print(f'  {key}: {value}')
if __name__ == '__main__':
    main()
