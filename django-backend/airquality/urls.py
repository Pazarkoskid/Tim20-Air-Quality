from django.urls import path
from airquality import views

urlpatterns = [
    path('', views.dashboard, name='home'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('map/', views.map_view, name='map'),
    path('history/', views.history_view, name='history'),
    path('forecast/', views.forecast_view, name='forecast'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/mark-read/', views.mark_all_read, name='mark_all_read'),
    path('notifications/delete/<int:pk>/', views.delete_notification, name='delete_notification'),
    path('notifications/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
    path('settings/', views.settings_view, name='settings'),
    # Export / Import
    path('export/csv/', views.export_csv, name='export_csv'),
    path('export/pdf/', views.export_pdf, name='export_pdf'),
    path('import/csv/', views.import_csv, name='import_csv'),
    # JSON API
    path('api/current/', views.api_current, name='api_current'),
    path('api/history/', views.api_history, name='api_history'),
    path('api/forecast/', views.api_forecast, name='api_forecast'),
    path('api/refresh/', views.api_refresh, name='api_refresh'),
    path('api/unread-count/', views.api_unread_count, name='api_unread_count'),
    # CR-002 & CR-003
    path('api/ranking/', views.api_ranking, name='api_ranking'),
    path('api/compare/', views.api_compare, name='api_compare'),
]
