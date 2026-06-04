from .activity import Activity
from django.utils import timezone
from django.db.models import Sum
from services.strava_service import StravaService, StravaRateLimitExceeded
from .models import GearMaintenanceManager, Gear
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)
def retrieve_and_save_activities(before, after, scan=False):
    """
        Retrieve activities from Strava between start and end date
        Uses the existing Activiy model mlethods for updating and handling post-update tasks
    """

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
                logger.error("Strava rate limit exceed, will not retry.")
                return count
        except Exception as e:
            logger.error("Error while fetching activities: %s", e)
            return count

        if len(activities) == 0:
            logger.info("No more actvities to fetch.")
            break

        if 'message' in activities:
            logger.error("Error from Strava API: %s", activities['message'])
            return count

        for activity_data in activities:
            logger.info("Processing activity: %s", activity_data['name'])

            # Check if activity is already in database
            activity, created = Activity.objects.get_or_create(stravaId=activity_data['id'])

            if created:
                logger.info("New activity created: %s", activity_data['name'])
            else:
                # TODO faire un vrai update ???
                logger.info("Activity already exists, updating: %s", activity_data['name'])

            # Update activity fields using the existing _update_fields method
            try:
                activity._update_fields(activity_data)
                activity.save()
                count += 1
            except Exception as e:
                logger.error("Error updating activity %s: %s", activity_data['id'], e)
                continue

            # trigger post-update tasks if needed
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

                except StravaRateLimitExceeded as e:
                    retry_after = e.retry_after
                    if retry_after:
                        logger.warning("Strava rate limit exceeded. retry in %s seconds", retry_after)
                        time.sleep(retry_after)
                        continue
                    else:
                        logger.error("Strava rate limit exceed, will not retry.")
                        break
                except Exception as e:
                    logger.error("Error during post-update tasks for activity %s: %s", activity_data['id'], e)

    logger.info("Retrieved and saved %s activities.", count)
    return count


def add_maintenance(form, gear):
    """
    Add a gear maintenance
    """

    maintenance = GearMaintenanceManager.objects.create()
    maintenance.date = datetime.combine(form.cleaned_data['date'],datetime.min.time())
    maintenance.date = timezone.make_aware(datetime.combine(form.cleaned_data['date'], datetime.min.time()))
    maintenance.description = form.cleaned_data['description']
    maintenance.notes = form.cleaned_data['notes']
    maintenance.periodicity_type = form.cleaned_data['periodicity_type']
    maintenance.periodicity_value = form.cleaned_data['periodicity_value']
    maintenance.gear = gear

    print(maintenance)

    maintenance.save()

def sync_maintenance(maint_id):
    """
    Synchonize gear time and distance elapsed at a given maintenance
    """

    service = GearMaintenanceManager.get(id=maint_id)
    result = Activity.objects.filter(gear=service.gear, startDate__lte=service.date).aggregate(
        distance=Sum('distance'), time=Sum('moving_time')
    )

    service.gear_distance = result['total_distance'] or 0
    service.gear_time = result['total_time'] or 0

    service.save()











