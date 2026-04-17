from django.contrib import admin
from airquality.models import AirQualityRecord, Forecast, Notification, UserProfile


@admin.register(AirQualityRecord)
class AirQualityRecordAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'aqi', 'pm25', 'pm10', 'no2', 'co', 'source']
    list_filter = ['source', 'timestamp']
    ordering = ['-timestamp']
    search_fields = ['source']


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = ['forecast_time', 'hours_ahead', 'predicted_aqi', 'predicted_pm25', 'confidence']
    ordering = ['forecast_time']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'aqi_value', 'read', 'created_at']
    list_filter = ['read']
    ordering = ['-created_at']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'aqi_threshold', 'notifications_enabled']
