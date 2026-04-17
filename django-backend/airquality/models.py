from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    aqi_threshold = models.IntegerField(default=100)
    notifications_enabled = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    notify_push = models.BooleanField(default=True)

    def __str__(self):
        return f'Profile of {self.user.username}'


class AirQualityRecord(models.Model):
    SOURCE_CHOICES = [('openweather', 'OpenWeather'), ('mock', 'Mock Data'), ('import', 'Imported')]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    aqi = models.FloatField()
    pm25 = models.FloatField(null=True, blank=True)   # µg/m³
    pm10 = models.FloatField(null=True, blank=True)   # µg/m³
    co = models.FloatField(null=True, blank=True)     # µg/m³
    no2 = models.FloatField(null=True, blank=True)    # µg/m³
    o3 = models.FloatField(null=True, blank=True)     # µg/m³
    so2 = models.FloatField(null=True, blank=True)    # µg/m³
    nh3 = models.FloatField(null=True, blank=True)    # µg/m³
    lat = models.FloatField(default=41.9981)
    lon = models.FloatField(default=21.4254)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='openweather')

    class Meta:
        ordering = ['-timestamp']

    def aqi_label(self):
        if self.aqi <= 50:
            return ('Добар', 'good')
        elif self.aqi <= 100:
            return ('Умерено', 'moderate')
        elif self.aqi <= 150:
            return ('Нездрав за чувствителни', 'sensitive')
        elif self.aqi <= 200:
            return ('Нездрав', 'unhealthy')
        elif self.aqi <= 300:
            return ('Многу нездрав', 'very-unhealthy')
        else:
            return ('Опасен', 'hazardous')

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'aqi': self.aqi,
            'pm25': self.pm25,
            'pm10': self.pm10,
            'co': self.co,
            'no2': self.no2,
            'o3': self.o3,
            'so2': self.so2,
            'nh3': self.nh3,
            'source': self.source,
        }

    def __str__(self):
        return f'AQI {self.aqi} @ {self.timestamp}'


class Forecast(models.Model):
    generated_at = models.DateTimeField(default=timezone.now)
    forecast_time = models.DateTimeField()
    hours_ahead = models.IntegerField()
    predicted_aqi = models.FloatField()
    predicted_pm25 = models.FloatField(null=True, blank=True)
    predicted_pm10 = models.FloatField(null=True, blank=True)
    confidence = models.FloatField(default=0.8)

    class Meta:
        ordering = ['forecast_time']

    def to_dict(self):
        return {
            'id': self.id,
            'generated_at': self.generated_at.isoformat(),
            'forecast_time': self.forecast_time.isoformat(),
            'hours_ahead': self.hours_ahead,
            'predicted_aqi': self.predicted_aqi,
            'predicted_pm25': self.predicted_pm25,
            'predicted_pm10': self.predicted_pm10,
            'confidence': self.confidence,
        }

    def __str__(self):
        return f'Forecast +{self.hours_ahead}h AQI={self.predicted_aqi}'


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    aqi_value = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Notification for {self.user.username}: {self.message[:50]}'
