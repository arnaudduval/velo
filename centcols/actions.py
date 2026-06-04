from collections import OrderedDict
from datetime import datetime

from django.db.models import Q, Max, Sum
from django.utils import timezone

from .activity import Activity
from .models import Col, Gear, GearMaintenanceManager, OSMImport, Tile, DurabilityIndicator
from services.strava_service import StravaService, StravaRateLimitExceeded

import logging
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility functions (called by views, not by the maintenance registry)
# ---------------------------------------------------------------------------

def retrieve_and_save_activities(before, after, scan=False):
    """Retrieve activities from Strava between start and end date."""
    service = StravaService()
    page = 0
    per_page = 100
    max_page = 1000
    count = 0

    while True:
        page += 1
        if page > max_page:
            logger.warning("Maximum number of pages (%s) reached.", max_page)
            break

        try:
            activities = service.get_activities(page=page, per_page=per_page, before=before, after=after)
        except StravaRateLimitExceeded as e:
            retry_after = e.retry_after
            if retry_after:
                logger.warning("Strava rate limit exceeded. retry in %s seconds", retry_after)
                time.sleep(retry_after)
                continue
            else:
                logger.error("Strava rate limit exceeded, will not retry.")
                return count
        except Exception as e:
            logger.error("Error while fetching activities: %s", e)
            return count

        if len(activities) == 0:
            logger.info("No more activities to fetch.")
            break

        if not isinstance(activities, list):
            logger.error("Unexpected response from Strava API.")
            return count

        for activity_data in activities:
            logger.info("Processing activity: %s", activity_data['name'])
            activity, created = Activity.objects.get_or_create(stravaId=activity_data['id'])
            try:
                activity._update_fields(activity_data)
                count += 1
            except Exception as e:
                logger.error("Error updating activity %s: %s", activity_data['id'], e)
                continue

            if scan:
                try:
                    if not activity.detailsHandled:
                        activity.scan()
                    if not activity.streamsHandled:
                        activity.get_streams()
                    if not activity.cp_curveHandled:
                        activity.compute_cp_curve()
                    if not activity.tilesHandled:
                        activity.do_check_tiles(zoom=14)
                except StravaRateLimitExceeded:
                    logger.error("Strava rate limit exceeded during post-update tasks.")
                    break
                except Exception as e:
                    logger.error("Error during post-update tasks for activity %s: %s", activity_data['id'], e)

    logger.info("Retrieved and saved %s activities.", count)
    return count


def add_maintenance(form, gear):
    """Add a gear maintenance record from a validated form."""
    maintenance = GearMaintenanceManager.objects.create(
        date=timezone.make_aware(datetime.combine(form.cleaned_data['date'], datetime.min.time())),
        description=form.cleaned_data['description'],
        notes=form.cleaned_data['notes'],
        periodicity_type=form.cleaned_data['periodicity_type'],
        periodicity_value=form.cleaned_data['periodicity_value'],
        gear=gear,
    )
    return maintenance


# ---------------------------------------------------------------------------
# Maintenance action functions
# Each takes no arguments and returns a human-readable result string.
# ---------------------------------------------------------------------------

def action_fetch_details():
    """Fetch detailed polyline for Ride/VirtualRide activities that lack it."""
    activities = Activity.objects.filter(
        Q(Type="Ride") | Q(Type="VirtualRide"), commute=False, detailsHandled=False
    ).order_by('startDate')
    count = sum(1 for a in activities if a.scan())
    return f"{count} activité(s) traitée(s)."


def action_fetch_streams():
    """Fetch power/altitude streams for Ride/VirtualRide activities that lack them."""
    activities = Activity.objects.filter(
        Q(Type="Ride") | Q(Type="VirtualRide"), commute=False, streamsHandled=False
    ).order_by('startDate')
    count = 0
    for activity in activities:
        if not activity.get_streams():
            break
        count += 1
    return f"{count} activité(s) traitée(s)."


def action_check_passes():
    """Find mountain passes for activities that have a polyline but no pass data."""
    activities = Activity.objects.filter(
        Type="Ride", commute=False, detailsHandled=True, colsHandled=False
    ).order_by('startDate')
    count = 0
    for activity in activities:
        activity.do_check_passes()
        count += 1
    return f"{count} activité(s) scannée(s)."


def action_compute_cp_curves():
    """Compute critical power curves for activities that have streams but no CP curve."""
    activities = Activity.objects.filter(
        Q(Type="Ride") | Q(Type="VirtualRide"), commute=False,
        streamsHandled=True, cp_curveHandled=False
    ).order_by('startDate')
    count = sum(1 for a in activities if a.compute_cp_curve())
    return f"{count} courbe(s) CP calculée(s)."


def action_compute_tiles():
    """Find visited map tiles (zoom 14) for activities that don't have them yet."""
    activities = Activity.objects.filter(
        Type="Ride", tilesHandled=False, detailsHandled=True
    ).order_by('startDate')
    count = 0
    for activity in activities:
        activity.do_check_tiles(zoom=14)
        count += 1
    return f"{count} activité(s) traitée(s)."


def action_sync_gear():
    """Sync full gear details from Strava for activities whose gear has no raw data."""
    count = 0
    for activity in Activity.objects.order_by('startDate'):
        if activity.gear_id and activity.gear.raw_data == {}:
            if activity.sync_gear_details():
                count += 1
    return f"{count} matériel(s) synchronisé(s)."


def action_update_modified():
    """Fetch recent activities from Strava and update any that have changed."""
    result = Activity.objects.aggregate(Max('startDate'))
    if not result['startDate__max']:
        return "Aucune activité en base."

    import ciso8601
    after = time.mktime(ciso8601.parse_datetime("20200101").timetuple())

    service = StravaService()
    page = 0
    modified_count = 0

    while True:
        page += 1
        if page > 1000:
            break
        activities = service.get_activities(
            page=page, per_page=200,
            before=result['startDate__max'].timestamp(),
            after=after,
        )
        if not activities:
            break

        modified_ids = []
        for activity_data in activities:
            q = Activity.objects.filter(stravaId=activity_data['id'])
            if q.exists() and q[0].check_modified(activity_data):
                modified_ids.append(activity_data['id'])
            elif not q.exists():
                logger.warning("Activity %s not found in DB", activity_data['id'])

        for strava_id in modified_ids:
            q = Activity.objects.filter(stravaId=strava_id)
            if q.exists():
                q[0].update()
                modified_count += 1

    return f"{modified_count} activité(s) mise(s) à jour."


def action_compute_durability():
    """Compute durability results for all defined indicators and eligible activities."""
    indicators = list(DurabilityIndicator.objects.all())
    if not indicators:
        return "Aucun indicateur de durabilité défini."

    activities = Activity.objects.filter(
        Q(Type="Ride") | Q(Type="VirtualRide"), commute=False, streamsHandled=True
    ).order_by('startDate')

    total = 0
    for activity in activities:
        for indicator in indicators:
            if activity.compute_durability(indicator):
                total += 1
    return f"{total} résultat(s) calculé(s)."


def action_reset_passes():
    """[DANGER] Delete all mountain passes and OSM imports, and reset activity flags."""
    for activity in Activity.objects.filter(colsHandled=True):
        activity.climbs.clear()
        activity.colsHandled = False
        activity.save()
    count = Col.objects.count()
    Col.objects.all().delete()
    OSMImport.objects.all().delete()
    return f"{count} col(s) supprimé(s), imports OSM réinitialisés."


def action_reset_tiles():
    """[DANGER] Delete all visited tiles and reset activity flags."""
    count = 0
    for activity in Activity.objects.filter(tilesHandled=True):
        activity.visited_tiles.clear()
        activity.tilesHandled = False
        activity.save()
        count += 1
    Tile.objects.all().delete()
    return f"Tuiles supprimées pour {count} activité(s)."


# ---------------------------------------------------------------------------
# Registry — ordered: normal actions first, dangerous ones last
# ---------------------------------------------------------------------------

MAINTENANCE_ACTIONS = OrderedDict([
    ('fetch_details', {
        'label': 'Récupérer les détails (polyline)',
        'description': 'Ride/VirtualRide non-commute sans polyline détaillée.',
        'dangerous': False,
        'fn': action_fetch_details,
    }),
    ('fetch_streams', {
        'label': 'Récupérer les streams',
        'description': 'Puissance, altitude, etc. pour Ride/VirtualRide sans streams.',
        'dangerous': False,
        'fn': action_fetch_streams,
    }),
    ('check_passes', {
        'label': 'Scanner les cols',
        'description': 'Recherche les cols franchis pour les Ride avec polyline.',
        'dangerous': False,
        'fn': action_check_passes,
    }),
    ('compute_cp_curves', {
        'label': 'Calculer les courbes CP',
        'description': 'Courbe de puissance critique pour Ride/VirtualRide avec streams.',
        'dangerous': False,
        'fn': action_compute_cp_curves,
    }),
    ('compute_tiles', {
        'label': 'Calculer les tuiles (zoom 14)',
        'description': 'Tuiles OSM visitées pour les Ride avec polyline.',
        'dangerous': False,
        'fn': action_compute_tiles,
    }),
    ('sync_gear', {
        'label': 'Synchroniser les matériels',
        'description': 'Met à jour les détails Strava des matériels sans données.',
        'dangerous': False,
        'fn': action_sync_gear,
    }),
    ('update_modified', {
        'label': 'Mettre à jour les activités modifiées',
        'description': 'Recherche et met à jour les activités modifiées depuis Strava.',
        'dangerous': False,
        'fn': action_update_modified,
    }),
    ('compute_durability', {
        'label': 'Calculer les indicateurs de durabilité',
        'description': 'Calcule les résultats pour tous les indicateurs définis.',
        'dangerous': False,
        'fn': action_compute_durability,
    }),
    ('reset_passes', {
        'label': 'Supprimer tous les cols',
        'description': 'Supprime tous les cols, les imports OSM et réinitialise les activités.',
        'dangerous': True,
        'fn': action_reset_passes,
    }),
    ('reset_tiles', {
        'label': 'Supprimer toutes les tuiles',
        'description': 'Supprime toutes les tuiles et réinitialise les activités.',
        'dangerous': True,
        'fn': action_reset_tiles,
    }),
])
