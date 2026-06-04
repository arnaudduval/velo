"""
Module handling activities
"""
import pickle
import base64
import logging
from io import BytesIO
import time

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import numpy as np
import polyline

from stravatools import osmtools
from services.strava_service import StravaService
from services.exceptions import StravaRateLimitExceeded, StravaResourceNotFound

from .models import Col, Tile, Stream, OSMImport, Gear
from .passes import retrieve_and_save_passes

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# Tolerance for mountain passes search
SEARCH_TOL = 20.

class Activity(models.Model):
    """
    Class representing an activity
    """
    name = models.CharField(max_length=1000, default='plop')
    distance = models.FloatField(default=0.)
    moving_time = models.IntegerField(default=0)
    elapsed_time = models.IntegerField(default=0)
    total_elevation_gain = models.FloatField(default=0.)
    stravaId = models.IntegerField(default=-1)
    startDate = models.DateTimeField(verbose_name="Début de l'activité (local)",
                                     default=timezone.now)
    Type = models.CharField(max_length=100, default='')
    sport_type = models.CharField(max_length=100, default='')
    summary_polyline = models.CharField(max_length=10000, default='', null=True)
    polyline = models.CharField(max_length=100000, default='', null=True)
    commute = models.BooleanField(default=False)
    trainer = models.BooleanField(default=False)
    manual = models.BooleanField(default=False)
    gear = models.ForeignKey(Gear, on_delete=models.SET_NULL, null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)


    climbs = models.ManyToManyField(Col)
    cp_curve = models.BinaryField(blank=True)
    visited_tiles = models.ManyToManyField(Tile)

    # Booleans for operations handling
    detailsHandled = models.BooleanField(default=False)     # TODO Trouver un autre nom plus descriptif
    colsHandled = models.BooleanField(default=False)
    streamsHandled = models.BooleanField(default=False)
    cp_curveHandled = models.BooleanField(default=False)


    tilesHandled = models.BooleanField(default=False)

    class Meta:
        verbose_name = "activity"

    def __str__(self):
        """
        Return object name
        """
        return self.name

    def _fetch_strava_activity(self) -> dict:
        """Centralize calls to Strava API."""
        service = StravaService()
        try:
            return service.get_activity(self.stravaId)
        except StravaRateLimitExceeded:
            logger.error("Strava rate limit exceeded")
            return None
        except StravaResourceNotFound:
            logger.error("Activity %s not found on Strava", self.stravaId)
            return None
        except Exception as e:
            logger.error("Error when getting activity %s", self.stravaId)
            raise

    def _fetch_strava_streams(self) -> dict:
        """Centralize calls to Strava API for streams."""
        service = StravaService()
        return service.get_activity_streams(self.stravaId)

    def _fetch_detailed_polyline(self) -> bool:
        """Get detailled polyline for activity."""
        strava_data = self._fetch_strava_activity()
        if not strava_data or 'map' not in strava_data:
            logger.warning("No map available for activity %s.", self.id)
            return False

        if 'polyline' in strava_data['map']:
            self.polyline = strava_data['map']['polyline']
            self.detailsHandled = True
            self.save()
            logger.debug("DEBUG fetch_detailed_polyline retourne True")
            logger.debug(f"DEBUG {self.polyline = }")
            return True
        return False


    def _update_fields(self, data: dict) -> None:
        """Update model fields from Strava data."""
        self.raw_data = data

        self.name = data.get('name', self.name)
        self.distance = data.get('distance', self.distance)
        self.moving_time = data.get('moving_time', self.moving_time)
        self.elapsed_time = data.get('elapsed_time', self.elapsed_time)
        self.total_elevation_gain = data.get('total_elevation_gain', self.total_elevation_gain)
        self.stravaId = data.get('id', self.stravaId)
        if 'start_date_local' in data:
            self.startDate = parse_datetime(data['start_date_local'])

        self.Type = data.get('type', self.Type)
        self.sport_type = data.get('sport_type', self.sport_type)

        if 'map' in data:
            if 'summary_polyline' in data['map']:
                self.summary_polyline = data['map']['summary_polyline']

        self.commute = data.get('commute', self.commute)
        self.trainer = data.get('trainer', self.trainer)
        self.manual = data.get('manual', self.manual)

        # Handle gear
        if 'gear_id' in data:
            gear_id = data['gear_id']
            if gear_id is not None:
                # Create a minimal Gear object if data only contain gear_id
                gear, created = Gear.objects.get_or_create(
                    strava_id=gear_id,
                    defaults={
                        'name': data.get('gear', {}).get('name', f"Gear {gear_id}"),
                        'brand_name': data.get('gear', {}).get('brand_name', ''),
                        'model_name': data.get('gear', {}).get('model_name', ''),
                        'distance': data.get('gear', {}).get('distance', 0.0),
                    }
                )
                gear.save()
                self.gear = gear
                logger.info(f"Gear {gear_id} {'créé' if created else 'existait déjà'} et assigné à l'activité {self.id}")
            else:
                self.gear = None


        self.save()

    def _handle_post_update(self) -> None:
        """Handle postprocessing after update (passes, streams, ..)."""
        if not self.detailsHandled:
            self.scan()
        if not self.streamsHandled:
            self.get_streams()
        if not self.cp_curveHandled:
            self.compute_cp_curve()
        if not self.tilesHandled:
            self.do_check_tiles(zoom=14)



    def update(self) -> bool:
        """Update activity from Strava and trigger postprocessing."""
        strava_data = self._fetch_strava_activity()
        if not strava_data:
            return False

        self._update_fields(strava_data)
        self._fetch_detailed_polyline()
        self.sync_gear_details()
        self._handle_post_update()
        return True


    # Nouvelle methode compute_cp_curve()
    def compute_cp_curve(self) -> bool:
        """
        Calcule la courbe de puissance critique (CP) pour l'activité.
        Pour chaque durée (fenêtre), on calcule la puissance moyenne maximale sur cette fenêtre.

        Returns:
            bool: True si la courbe CP a été calculée et sauvegardée, False sinon.
        """

        # Get 'time' and 'power' streams
        time_stream = Stream.objects.filter(activity=self, metric='time').first()
        watts_stream = Stream.objects.filter(activity=self, metric='watts').first()

        # Verify if streams exist
        if not time_stream or not watts_stream:
            print("Error: stream 'time' or 'watts' is missing for this activity.")
            return False

        # Get binary data
        try:
            time_data = pickle.loads(base64.b64decode(time_stream.data))
            watts_data = pickle.loads(base64.b64decode(watts_stream.data))
        except Exception as e:
            print(f"Erro while loading data: {e}")
            return False

        # Verify data
        if len(time_data) == 0 or len(watts_data) == 0:
            print("Error: time of power data is empty.")
            return False

        if len(time_data) != len(watts_data):
            print("Error: time and power array do not have the same length.")
            return False

        # Get total time and create dense array of power values
        max_time = int(np.max(time_data))
        dense_watts = np.zeros(max_time+1)

        # Fill dense power array
        for time, watts in zip(time_data,  watts_data):
            if time <= max_time:
                dense_watts[int(time)] = watts

        # Compute CP curve: for each duration w, find the maximum average power
        # over any contiguous window of w seconds.
        #
        # Naive approach (np.convolve in a loop) is O(n²) — too slow for rides
        # of several hours sampled at 1 Hz (~10 000 iterations × O(n) convolution).
        #
        # Instead, we precompute the cumulative sum once (O(n)), then the sum of
        # any window [i, i+w) is simply cumsum[i+w] - cumsum[i], making each
        # per-window max a single vectorised subtraction + np.max — O(n) per window
        # but with a much smaller constant than convolution.
        max_duration = len(dense_watts)
        cp_curve = np.zeros(max_duration)
        cumsum = np.concatenate([[0.], np.cumsum(dense_watts)])  # prepend 0 so cumsum[0]=0

        for window_size in range(1, max_duration + 1):
            window_sums = cumsum[window_size:] - cumsum[:max_duration - window_size + 1]
            cp_curve[window_size - 1] = np.max(window_sums) / window_size

        # save CP curve
        try:
            buffer = BytesIO()
            np.save(buffer, cp_curve, allow_pickle=True)
            self.cp_curve = buffer.getvalue()
            self.cp_curveHandled = True
            self.save()
            print(f"Courbe CP calculée et sauvegardée pour l'activité {self.id}.")
            return True
        except Exception as e:
            print(f"Error when saving CP curve: {e}")
            return False


    def do_check_passes(self):
        """Search and add passes to activity"""
        if not self.polyline:
            logger.warning(f"No polyline for activity {self.id}")
            return

        try:
            detail_poly = np.array(polyline.decode(self.polyline))

            # Check if bouding box already exists in cols tables
            imp = OSMImport.objects.filter(bboxBotLeftLat__lt = np.min(detail_poly[:,0]),
                                            bboxBotLeftLon__lt = np.min(detail_poly[:,1]),
                                            bboxTopRightLat__gt = np.max(detail_poly[:,0]),
                                            bboxTopRightLon__gt = np.max(detail_poly[:,1]))

            if not imp:
                retrieve_and_save_passes(np.min(detail_poly[:,0]), np.min(detail_poly[:,1]),
                                        np.max(detail_poly[:,0]), np.max(detail_poly[:,1]))

            # Get cols in activity bounding box
            for p in Col.objects.filter(latitude__gte = np.min(detail_poly[:,0]),
                                        longitude__gte = np.min(detail_poly[:,1]),
                                        latitude__lte = np.max(detail_poly[:,0]),
                                        longitude__lte = np.max(detail_poly[:,1])):
                if osmtools.point_in_polyline(detail_poly, p.latitude, p.longitude, SEARCH_TOL):
                    print(p.name)
                    self.climbs.add(p)

            self.colsHandled = True

            self.save()
        except Exception as e:
            logger.error(f"Error when searching passes for activity {self.id}: {e}")

    def do_check_tiles(self, zoom):
        """Check visited tiles for activity and given zoom level"""
        logger.info(f"Searching tiles in activity {self.name} ({self.id})")
        if not self.polyline or self.polyline == '':
            logger.warning("No polyline available for activity %s.", self.id)
            return

        try:
            detail_poly = np.array(polyline.decode(self.polyline))
            tiles = osmtools.visited_tiles_in_polyline(detail_poly, zoom)

            # Efface les tuiles existantes pour éviter les doublons
            self.visited_tiles.clear()

            for tile_data in tiles:
                tile, created = Tile.objects.get_or_create(
                    zoom=tile_data[2],
                    x=tile_data[0],
                    y=tile_data[1]
                )
                self.visited_tiles.add(tile)

            self.tilesHandled = True
            logger.info("tilesHandled set to True")
            self.save()
        except Exception as e:
            logger.error("Error when checking tiles for activity %s : %s", self.id, e)


    def get_streams(self):
        """retrieve streams for an activity"""
        try:
            streams = self._fetch_strava_streams()
        except StravaResourceNotFound:
            # Si la ressource n'est pas trouvée, on marque l'activité comme traitée
            self.streamsHandled = True
            logger.warning("Ressource non trouvée pour l'activité %s. Cela peut être dû à une saisie manuelle.", self.id)
            self.save()
            return True
        except Exception as e:
            logger.error("Error when getting streams for activity %s : %s", self.id, e)
            return False

        if not isinstance(streams, list):
            logger.error("Unexpected response format for streams of activity %s", self.id)
            return False

        Stream.objects.filter(activity=self).delete()

        for stream in streams:
            s = Stream()
            s.metric = stream['type']
            data = np.array(stream['data'])
            np_bytes = pickle.dumps(data)
            s.data = base64.b64encode(np_bytes)
            s.activity = self
            s.save()

        self.streamsHandled = True
        self.save()
        return True


    def scan(self) -> bool:
        """Récupère les détails de l'activité (polyline) et recherche les cols."""
        logger.debug(f"DEBUG SCAN {self.detailsHandled = }")

        if not self.detailsHandled:
            if not self._fetch_detailed_polyline():
                logger.warning("Cannot get detailled polyline for activity %s.", self.id)
                logger.debug("DEBUG SCAN fetch_detailed_polyline retourne False")

                return False

        if not self.polyline:
            logger.warning("No polyline available for activity %s.", self.id)
            logger.debug("DEBUG SCAN not self.polyline")

            return False

        logger.debug("DEBUG SCAN on a passé tous les return False")
        self.do_check_passes()
        return True

    def check_modified(self, activity_data):
        """Check if activity is different from the one passed as argument"""
        fields_to_check = [
            ('name', 'name'),
            ('distance', 'distance'),
            ('moving_time', 'moving_time'),
            ('elapsed_time', 'elapsed_time'),
            ('total_elevation_gain', 'total_elevation_gain'),
            ('startDate', 'start_date_local', parse_datetime),
            ('Type', 'type'),
            ('sport_type', 'sport_type'),
            ('summary_polyline', ('map', 'summary_polyline')),
            ('commute', 'commute'),
            ('trainer', 'trainer'),
            ('manual', 'manual'),
        ]
        modified = False
        for field, activity_key, *args in fields_to_check:
            if isinstance(activity_key, tuple):
                if activity_key[0] in activity_data and activity_key[1] in activity_data[activity_key[0]]:
                    current_value = getattr(self, field)
                    new_value = activity_data[activity_key[0]][activity_key[1]]
                    if isinstance(new_value, str) and new_value != current_value:
                        logger.info("modif : %s", field)
                        modified = True
            else:
                if activity_key in activity_data:
                    current_value = getattr(self, field)
                    new_value = activity_data[activity_key]
                    if args:
                        new_value = args[0](new_value)
                    if new_value != current_value:
                        logger.info("modif : %s", field)
                        modified = True

        # Specific handling for gear_id
        if 'gear_id' in activity_data:
            if self.gear is None:
                # If activity has a gear_id but self.gear is None, it is modified
                if activity_data['gear_id'] is not None:
                    logger.info("modif : gear_id (activity has a gear_id but gear is None)")
                    modified = True
            else:
                # If self.gear exists, compare strava_id
                if self.gear.strava_id != activity_data['gear_id']:
                    logger.info("modif : gear_id (activity has a gear but gear_id has changed)")
                    modified = True

        return modified

    def sync_gear_details(self):
        """
        Synchronize full details of activity gear
        """
        if not self.gear:
            return False

        gear = Gear.fetch_gear_details(self.gear.strava_id)
        if gear:
            self.gear = gear
            self.save()
            return True
        return False


    def verify_deleted(self):
        """Verify if activity has been deleted in Strava."""
        service = StravaService()
        try:
            activity = service.get_activity(self.stravaId)
        except StravaResourceNotFound:
            logger.warning("Activity %s not found on Strava", self.stravaId)
            return True
        except Exception as e:
            logger.warning("Error when getting strava activity %s: %s", self.stravaId, e)
            return False

        return False