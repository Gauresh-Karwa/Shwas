import logging
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from app.ingestion.pipeline import run_ingestion_cycle
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('shwas.scheduler')

def cpcb_ingestion_job():
    logger.info('Starting scheduled CPCB ingestion cycle')
    try:
        summary = run_ingestion_cycle()
        logger.info(f'Ingestion cycle complete: {summary}')
    except Exception as e:
        logger.error(f'Ingestion cycle FAILED: {type(e).__name__}: {e}')

def _job_listener(event):
    if event.exception:
        logger.error(f'Job {event.job_id} raised an unhandled exception.')
    else:
        logger.info(f'Job {event.job_id} finished normally.')

def main():
    scheduler = BlockingScheduler()
    scheduler.add_job(cpcb_ingestion_job, trigger='cron', minute=10, id='cpcb_ingestion', misfire_grace_time=300)
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    logger.info('Scheduler starting. CPCB ingestion will run every hour at :10.')
    logger.info(f'Current time: {datetime.now()}. Press Ctrl+C to stop.')
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info('Scheduler stopped.')
if __name__ == '__main__':
    main()
