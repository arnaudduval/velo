from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, wait_fixed
from django.conf import settings
from stravatools import StravaApp
from .exceptions import StravaRateLimitExceeded, StravaResourceNotFound, StravaAPIError, StravaAuthenticationError

import logging

logger = logging.getLogger(__name__)


class StravaService:
    def __init__(self):
        self.strava = StravaApp(
            client_id=int(settings.STRAVA_CLIENT_ID),
            client_secret=settings.STRAVA_CLIENT_SECRET
        )
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        try:
            # TODO verifier la durée de validité du token
            return self.strava.get_token(settings.STRAVA_ACCESS_TOKEN)
        except Exception as e:
            logger.error("Error while getting Strava access token: %s", e)
            raise StravaAuthenticationError("Strava authentication error.")

    def _handle_response(self, response):
        """
        Handle Strava API response and raise appropiated exceptions
        """

        if isinstance(response, dict):
            print(f"{response.get('message') = }")
            if response.get('message') == 'Rate Limit Exceeded':
                raise StravaRateLimitExceeded()
            if response.get('message') == 'Record not found':
                raise StravaResourceNotFound()
            if response.get('message') == 'Authorization error':
                raise StravaAuthenticationError("Strava authentication error.")
            if 'message' in response:
                if response['message'] == "Resource Not Found":
                    raise StravaResourceNotFound()
                raise StravaAPIError(f"Strava API error: {response['message']}")
        return response

    @retry(
            stop=stop_after_attempt(5),
            wait=wait_fixed(900),
            retry=retry_if_exception_type(StravaRateLimitExceeded)
    )
    def get_activity(self, activity_id: int) -> dict:
        """Récupère une activité depuis l'API Strava avec gestion des erreurs."""
        print(f"APPEL get_activity, {activity_id}")
        try:
            response = self.strava.get_activity(self.access_token, activity_id)
            return self._handle_response(response)
        except Exception as e:
            logger.error("Error when getting activity %s: %s", activity_id, e)
            raise

    @retry(
            stop=stop_after_attempt(5),
            wait=wait_fixed(180),
            retry=retry_if_exception_type(StravaRateLimitExceeded)
    )
    def get_activity_streams(self, activity_id: int) -> dict:
        """Récupère les streams d'une activité."""
        try:
            response =  self.strava.get_activity_streams(self.access_token, activity_id)
            return self._handle_response(response)
        except Exception as e:
            print(f"Erreur lors de la récupération des streams pour {activity_id}: {e}")
            raise

    @retry(
            stop=stop_after_attempt(5),
            wait=wait_fixed(180),
            retry=retry_if_exception_type(StravaRateLimitExceeded)
    )
    def get_activities(self, page: int, per_page: int, before, after) -> list:
        """Get a list of actvities."""
        try:
            response =  self.strava.get_activities(self.access_token, per_page=per_page, page=page, before=before, after=after)
            return self._handle_response(response)
        except Exception as e:
            logger.error("Error when getting activities: %s", e)
            raise

    @retry(
            stop=stop_after_attempt(5),
            wait=wait_fixed(180),
            retry=retry_if_exception_type(StravaRateLimitExceeded)
    )
    def get_gear(self, gear_id: str) -> dict:
        """Get a gear"""
        try:
            response = self.strava.get_gear(self.access_token, gear_id)
            return self._handle_response(response)
        except Exception as e:
            print(f"Error when getting gear: {e}")
            raise
