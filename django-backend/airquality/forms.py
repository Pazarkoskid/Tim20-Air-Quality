from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from airquality.models import UserProfile


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, label='Е-пошта')
    username = forms.CharField(label='Корисничко име')

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            UserProfile.objects.get_or_create(user=user)
        return user


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=False, label='Име')
    last_name = forms.CharField(max_length=30, required=False, label='Презиме')
    email = forms.EmailField(required=True, label='Е-пошта')

    class Meta:
        model = UserProfile
        fields = ['aqi_threshold', 'notifications_enabled', 'notify_email', 'notify_push']
        labels = {
            'aqi_threshold': 'Праг за AQI известувања',
            'notifications_enabled': 'Овозможи известувања',
            'notify_email': 'Е-пошта известувања',
            'notify_push': 'Push известувања',
        }


class HistoryFilterForm(forms.Form):
    PERIOD_CHOICES = [
        ('24h', 'Последни 24 часа'),
        ('7d', 'Последни 7 дена'),
        ('30d', 'Последни 30 дена'),
        ('custom', 'Прилагодено'),
    ]
    period = forms.ChoiceField(choices=PERIOD_CHOICES, required=False, label='Период')
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label='Од')
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label='До')
