"""
Run with: python manage.py runscheduler
Fetches air quality data every hour and generates forecasts every 6 hours.
"""

from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)


def fetch_job():
    from airquality.services import fetch_air_quality, save_record_and_notify
    logger.info("Scheduler: fetching air quality data...")
    data = fetch_air_quality()
    save_record_and_notify(data)


def forecast_job():
    from airquality.services import generate_forecast
    logger.info("Scheduler: generating forecasts...")
    generate_forecast()


class Command(BaseCommand):
    help = 'Start APScheduler to fetch air quality data hourly'

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone='Europe/Skopje')

        # Fetch every hour
        scheduler.add_job(fetch_job, CronTrigger(minute=0), id='fetch_air_quality',
                          max_instances=1, replace_existing=True)

        # Forecast every 6 hours
        scheduler.add_job(forecast_job, CronTrigger(hour='*/6'), id='generate_forecast',
                          max_instances=1, replace_existing=True)

        self.stdout.write(self.style.SUCCESS('Scheduler started. Fetching every hour.'))
        try:
            # Run immediately on start
            fetch_job()
            forecast_job()
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            self.stdout.write(self.style.WARNING('Scheduler stopped.'))
