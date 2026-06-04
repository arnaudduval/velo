from django.db import models
from django.utils import timezone

from services.strava_service import StravaService


import logging
logger = logging.getLogger(__name__)


class Gear(models.Model):
    """
    Model representing a gear (bike, shoes, ...)
    """
    strava_id = models.CharField(max_length=24, unique=True, verbose_name="Strava ID of gear")
    name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=255, blank=True, null=True)
    model_name = models.CharField(max_length=255, blank=True, null=True)
    distance = models.FloatField(default=0.0)

    raw_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.name} ({self.brand_name} {self.model_name})"

    class Meta:
        verbose_name = "Gear"
        verbose_name_plural = "Gears"

    @classmethod
    def fetch_gear_details(cls, gear_id):
        """
        Get details of a gear from Strava
        """
        try:
            service = StravaService()
            gear_data = service.get_gear(gear_id)
            gear, created = cls.objects.get_or_create(
                strava_id = gear_id,
                defaults={
                    'name': gear_data.get('name', f"Gear {gear_id}"),
                    'brand_name': gear_data.get('brand_name', ''),
                    'model_name': gear_data.get('model_name', ''),
                    'distance': gear_data.get('distance', 0.0),
                    'raw_data': gear_data
                }
            )

            if not created:
                # Update fields if gear already exists
                for field in ['name', 'brand_name', 'model_name', 'distance']:
                    setattr(gear, field, gear_data.get(field, getattr(gear, field)))
                gear.raw_data = gear_data
                gear.save()

            return gear
        except Exception as e:
            logger.error("Error when fetching gear details %s: %s", gear_id, e)
            return None


class GearMaintenanceManager(models.Model):
    date = models.DateTimeField(verbose_name="date de la maintenance", default=timezone.now, blank=False)
    gear = models.ForeignKey(Gear, on_delete=models.SET_NULL, null=True, blank=False)
    description = models.CharField(max_length=1000, default='', blank=False)
    notes = models.TextField(blank=True, null=True)
    gear_distance = models.FloatField(default=0.)
    gear_time = models.IntegerField(default=0)

    PERIODICITY_CHOICES = [
        ('none', 'Aucun'),
        ('elapsed', 'Temps écoulé (mois)'),
        ('hours', 'Heures'),
        ('km', 'Kilomètres'),
    ]

    periodicity_type = models.CharField(
        max_length=7,
        choices=PERIODICITY_CHOICES,
        verbose_name="Type de périodicité",
        blank=False,
        null=False
    )

    periodicity_value = models.PositiveIntegerField(
        verbose_name="Valeur de périodicité",
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.gear} - {self.description} ({self.periodicity_value} {self.periodicity_type})"

    class Meta:
        verbose_name = "Maintenance"
        verbose_name_plural = "Maintenances"

    def get_periodicity_display(self):
        if self.periodicity_type == 'none':
            return ''

        if self.periodicity_type == 'km':
            return f"{self.periodicity_value} km"
        if self.periodicity_type == 'hours':
            return f"{self.periodicity_value} heures de fonctionnement"
        if self.periodicity_type == 'elapsed':
            return f"{self.periodicity_value} mois"
        return ""

    def get_elapsed_hours_km(self):
        return 0

class DurabilityPower(models.Model):
    """
    Class representing critical power after a given energy expenditure
    """
    duration_seconds = models.IntegerField(default=0)
    power_watts = models.IntegerField(default=0)
    energy_kJ = models.IntegerField(default=0)



class Col(models.Model):
    name = models.CharField(max_length=255, default="unnamed")
    elevation = models.FloatField(null=True)
    latitude = models.FloatField(default=0.)
    longitude = models.FloatField(default=0.)
    osmId = models.IntegerField(default=-1)

    class Meta:
        verbose_name = "Pass"
        verbose_name_plural = "Passes"
        ordering = ['name']

    def __str__(self):
        """
        Cette méthode permet de reconnaître plus facilement
        les différents objets dans l'administration
        """
        return self.name #+'('+str(elevation)+')'

class Tile(models.Model):
    zoom = models.IntegerField()
    x = models.IntegerField()
    y = models.IntegerField()

    class Meta:
        verbose_name = "Tile"

    def __str__(self):
        return str(self.zoom)+'/'+str(self.x)+'/'+str(self.y)



class Stream(models.Model):
    metric = models.CharField(max_length=30)
    data = models.BinaryField()
    activity = models.ForeignKey('Activity', on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Stream"


    def __str__(self):
        return self.metric




class OSMImport(models.Model):
    bboxBotLeftLat = models.FloatField(default=0.)
    bboxBotLeftLon = models.FloatField(default=0.)
    bboxTopRightLat = models.FloatField(default=0.)
    bboxTopRightLon = models.FloatField(default=0.)
    date = models.DateTimeField(default=timezone.now,
                                verbose_name="Date de réalisation de l'import")

    class Meta:
        verbose_name = "OSM import"
        ordering = ['date']

    def __str__(self):
        return str(self.date)+' ('+str(self.bboxBotLeftLat)+','+str(self.bboxBotLeftLon)+ \
                + '),'+str(self.bboxTopRightLat)+','+str(self.bboxTopRightLon)+')'

