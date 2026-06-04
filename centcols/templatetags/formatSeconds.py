from django import template
import math

register = template.Library()

@register.filter()
def formatSeconds(s):
    hours = math.floor(s / 3600)
    mins = math.floor((s - (hours*3600)) / 60);
    secs = math.floor(s - (mins * 60) - (hours*3600));

    return "%d:%02d:%02d" % (hours, mins, secs);

@register.filter()
def formatSecondsToHours(s):
    hours = math.floor(s / 3600)

    return "%d" % (hours);
