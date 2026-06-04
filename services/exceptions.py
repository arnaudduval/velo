class StravaAPIError(Exception):
    """Base exception for Strava API errors"""
    pass

class StravaRateLimitExceeded(StravaAPIError):
    """
    Exception raised when Strava API max requests number is reached
    """
    def __init__(self, message="Max number of Strava API requets reached."):
        self.message = message
        super().__init__(self.message)

class StravaResourceNotFound(StravaAPIError):
    """
    Exception raised when requested resource is not found
    """
    pass

class StravaAuthenticationError(StravaAPIError):
    """
    Exception raised in case of authentication error
    """
    pass