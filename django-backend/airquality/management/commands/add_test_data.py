from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from airquality.models import AirQualityRecord
import random


class Command(BaseCommand):
    help = 'Add test air quality data for development'

    def handle(self, *args, **options):
        # Clear existing test data
        AirQualityRecord.objects.filter(source='test').delete()

        now = timezone.now()
        base_aqi = 45

        self.stdout.write('Adding test data...')

        for i in range(30):  # 30 days of data
            for hour in range(0, 24, 2):  # Every 2 hours
                timestamp = now - timedelta(days=29 - i, hours=hour)


                trend_factor = i * 0.3
                # Daily variation (worse during rush hours)
                hour_factor = 5 if 7 <= hour <= 9 or 17 <= hour <= 19 else 0
                # Random noise
                noise = random.gauss(0, 3)

                aqi = base_aqi + trend_factor + hour_factor + noise
                aqi = max(10, min(120, aqi))

                AirQualityRecord.objects.create(
                    timestamp=timestamp,
                    aqi=round(aqi, 1),
                    pm25=round(aqi * 0.6 + random.gauss(0, 2), 2),
                    pm10=round(aqi * 0.8 + random.gauss(0, 3), 2),
                    co=round(200 + random.gauss(0, 20), 2),
                    no2=round(15 + random.gauss(0, 5), 2),
                    o3=round(60 + random.gauss(0, 10), 2),
                    so2=round(5 + random.gauss(0, 2), 2),
                    nh3=round(3 + random.gauss(0, 1), 2),
                    source='test'
                )

        count = AirQualityRecord.objects.filter(source='test').count()
        self.stdout.write(
            self.style.SUCCESS(f'Successfully added {count} test records')
        )