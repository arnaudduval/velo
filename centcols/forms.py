from django import forms
from django.utils import timezone
from .models import GearMaintenanceManager

class ImportOSMForm(forms.Form):
    minLat = forms.FloatField(min_value=-90., max_value=90.)
    maxLat = forms.FloatField(min_value=-90., max_value=90.)
    minLon = forms.FloatField(min_value=-180., max_value=180.)
    maxLon = forms.FloatField(min_value=-180., max_value=180.)

class ImportStravaForm(forms.Form):
    startDate = forms.DateField(label='Date de début',
                                input_formats=['%d/%m/%Y'],
                                widget=forms.TextInput(attrs=
           {
            'class':'datepicker'
           }))
    endDate = forms.DateField(label='Date de fin',
                              input_formats=['%d/%m/%Y'],
                              widget=forms.TextInput(attrs=
           {
            'class':'datepicker'
           }))

class AddGearMaintenance(forms.Form):

    date = forms.DateField(label='Date',
                                input_formats=['%d/%m/%Y'],
                                widget=forms.TextInput(attrs=
           {
            'class':'datepicker'
           }))

    description = forms.CharField(
        label="Description",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    notes = forms.CharField(
        label="Notes",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,  # Nombre de lignes visibles
            'placeholder': 'Notes...'
        }),
        required=False
    )

    periodicity_type = forms.ChoiceField(
        label="Type de périodicité",
        choices=GearMaintenanceManager.PERIODICITY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    periodicity_value = forms.IntegerField(
        label="Valeur de périodicité",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
        required=False
    )

