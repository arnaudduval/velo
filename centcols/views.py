import logging


from django.core.checks import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.contrib import messages
from django.urls import reverse
from datetime import datetime
from .activity import Activity
from .models import Col, OSMImport, Stream, Tile, Gear, GearMaintenanceManager
from .forms import ImportOSMForm, ImportStravaForm, AddGearMaintenance
from .actions import retrieve_and_save_activities, add_maintenance
from .passes import retrieve_and_save_passes

#import centcols_tools
from stravatools import StravaApp
from stravatools import osmtools
import polyline
import numpy as np
import math
import pickle
import base64
import json
from io import BytesIO


from django.db.models.functions import TruncDay, TruncMonth

logger = logging.getLogger(__name__)


def cp_best_json(request, startday, startmonth, startyear, endday, endmonth, endyear):
    """
    Retourne la courbe CP entre la date de début et la date de fin
    """
    # TODO : ajouter un filtre pour le ytpe de vélo et le HT

    startDate = datetime(startyear, startmonth, startday, 0, 0, 0)
    endDate = datetime(endyear, endmonth, endday, 23, 59, 59)

    activities = Activity.objects.filter(startDate__gte=startDate, startDate__lte=endDate, Type="Ride", cp_curveHandled=True, commute=False)

    max_cp = np.array([0.])

    for activity in activities:
        cp_curve = np.load(BytesIO(activity.cp_curve), allow_pickle=True)
        if len(cp_curve) > len(max_cp):
            old_cp = max_cp
            max_cp = np.zeros_like(cp_curve)
            max_cp[:len(old_cp)] = old_cp

        max_cp[:len(cp_curve)] = np.maximum(cp_curve, max_cp[:len(cp_curve)])

    if len(max_cp) == 1 and max_cp[0] == 0.:
        return HttpResponse(json.dumps({'datasets': []}), content_type="application/json")

    data = {}
    duration = np.arange(len(max_cp), dtype=float) + 1

    data['datasets'] = []
    metric = {}
    metric['label'] = 'CP'
    metric['data'] = []
    for i in range(len(max_cp)):
        value = {'x': duration[i], 'y': max_cp[i]}
        metric['data'].append(value)
    metric['fill'] = True
    metric['borderColor'] = '#cc1e1e'
    metric['backgroundColor'] = '#e49191'
    metric['pointRadius'] = 2
    data['datasets'].append(metric)

    return HttpResponse(json.dumps(data), content_type="application/json")


# Nouvelle version de cp_curve_json:
def cp_curve_json(request, id):
    """
    Return CP curve as a JSON
    CP curve is stored as a Numpy array serialized in 'cp_curve' member
    """
    try:
        activity = Activity.objects.get(id=id)
    except Activity.DoesNotExist:
        raise Http404('Activity not found.')

    if not activity.cp_curve or not activity.cp_curveHandled:
        print(f'{activity.cp_curveHandled = }')
        raise Http404("CP curve has not been computed for this activity.")

    # deserialize CP curve
    try:
        cp_curve = np.load(BytesIO(activity.cp_curve), allow_pickle=True)
    except Exception as e:
        raise Http404(f"Error when deserializing CP curve: {e}")

    # Create data for JSON
    data = {
        'labels': [],   # Optional, can be use to add labels on X axis
        'datasets': [{
            'label': 'Critical Power (Watts)',
            'data': [],
            'fill': True,
            'borderColor': '#cc1e1e',
            'backgroundColor': '#e49191',
            'pointRadius': 2,
            'tension': 0.4  # Optionnal, smooth the curve
        }]
    }

    # Fill data
    for i in range(len(cp_curve)):
        data['datasets'][0]['data'].append({
            'x': float(i + 1),  # Duration in seconds
            'y': float(cp_curve[i]) # Critical power in watts
        })

    return HttpResponse(json.dumps(data), content_type="application/json")

# def cp_curve_json(request, id):
#     activity = Activity.objects.get(id = id)
#     if not activity.cp_curve:
#         raise Http404

#     cp_curve = pickle.loads(base64.b64decode(activity.cp_curve))
#     duration = np.arange(1, len(cp_curve), dtype=float)

#     data = {}

#     data['datasets'] = []
#     metric = {}
#     metric['label'] = 'CP'
#     metric['data'] = []
#     for i in range(len(cp_curve)-1):
#         value = {'x': duration[i],'y':cp_curve[i]}
#         metric['data'].append(value)
#     metric['fill'] = True
#     metric['borderColor'] = '#cc1e1e'
#     metric['backgroundColor'] = '#e49191'
#     metric['pointRadius'] = 2
#     data['datasets'].append(metric)

#     return HttpResponse(json.dumps(data), content_type="application/json")



def time_streams_json(request, id):
    """Return Test data for a chart"""
    streams = Stream.objects.filter(activity__id = id)
    if streams.count() == 0:
        raise Http404



    data = {}
    data['labels'] = pickle.loads(base64.b64decode(streams.get(metric='time').data)).tolist()
    data['datasets'] = []
    for stream in streams:
        if stream.metric == 'watts':
            metric = {}
            metric['label'] = 'Puissance'
            metric['data'] = pickle.loads(base64.b64decode(streams.get(metric='watts').data)).tolist()
            metric['fill'] = False
            metric['borderColor'] = '#cc1e1e'
            metric['borderWidth'] = '1'
            metric['pointRadius'] = 0
            data['datasets'].append(metric)
        if stream.metric == 'altitude':
            metric = {}
            metric['label'] = 'Altitude'
            metric['data'] = pickle.loads(base64.b64decode(streams.get(metric='altitude').data)).tolist()
            metric['fill'] = True
            metric['borderColor'] = '#d8be47'
            metric['backgroundColor'] = '#eed560'
            metric['pointRadius'] = 0
            data['datasets'].append(metric)


    return HttpResponse(json.dumps(data), content_type="application/json")






def all_climbed_json(request):
    """Return all climbed passes as JSON"""
    # TODO trouver un meilleur filtre
    cols = Col.objects.filter(activity__name__contains='').order_by('-elevation').distinct()

    feature_set = []
    for col in cols:
        feature = {}
        feature['type'] = 'Feature'

        properties = {}
        properties['name'] = col.name
        properties['popupContent'] = col.name+' ('+str(int(col.elevation))+' m)'
        feature['properties'] = properties

        geometry = {}
        geometry['type'] = 'Point'
        geometry['coordinates'] = [col.longitude, col.latitude]
        feature['geometry'] = geometry

        feature_set.append(feature)


    return HttpResponse(json.dumps(feature_set), content_type="application/json")

def climbed_json(request, id):
    """Return climbed path of an activity as JSON"""
    cols = Activity.objects.get(id=id).climbs.all()

    feature_set = []
    for col in cols:
        feature = {}
        feature['type'] = 'Feature'

        properties = {}
        properties['name'] = col.name
        properties['popupContent'] = col.name+' ('+str(int(col.elevation))+' m)'
        feature['properties'] = properties

        geometry = {}
        geometry['type'] = 'Point'
        geometry['coordinates'] = [col.longitude, col.latitude]
        feature['geometry'] = geometry

        feature_set.append(feature)

    return HttpResponse(json.dumps(feature_set), content_type="application/json")


def visited_tiles_json(request, id):
    """Return visited tiles of a given activity"""
    #TODO : use zoom level as a parameter
    zoom = 14
    tiles = Activity.objects.get(id=id).visited_tiles.filter(zoom=zoom)

    data = []
    for tile in tiles:
        geometry = {}
        geometry['type'] = 'Polygon'
        xtile = tile.x
        ytile = tile.y
        NW = osmtools.num2deg(xtile, ytile, zoom)
        NE = osmtools.num2deg(xtile+1, ytile, zoom)
        SE = osmtools.num2deg(xtile+1, ytile+1, zoom)
        SW = osmtools.num2deg(xtile, ytile+1, zoom)
        geometry['coordinates'] = [[[NW[1],NW[0]],[NE[1],NE[0]],[SE[1],SE[0]],[SW[1],SW[0]],[NW[1],NW[0]]]]
        data.append(geometry)

    return HttpResponse(json.dumps(data), content_type="application/json")

def all_sumtrack_json(request):
    """Return JSON containing all activities summary track"""
    activities = Activity.objects.exclude(summary_polyline = None)
    dataset = []

    for activity in activities:
        data = {}
        data['type'] = 'LineString'
        data['coordinates'] = polyline.decode(activity.summary_polyline, geojson=True)

        dataset.append(data)

    return HttpResponse(json.dumps(dataset), content_type="application/json")


def sumtrack_json(request,id):
    """Return activity summary track as json"""
    activity = Activity.objects.get(id=id)


    data = {}
    data['type'] = 'LineString'
    data['coordinates'] = polyline.decode(activity.summary_polyline, geojson=True)

    return HttpResponse(json.dumps(data), content_type="application/json")

def track_json(request,id):
    """Return activity detailled track as json"""
    activity = Activity.objects.get(id=id)


    data = {}
    data['type'] = 'LineString'
    data['coordinates'] = polyline.decode(activity.polyline, geojson=True)

    return HttpResponse(json.dumps(data), content_type="application/json")



def graph_cp(request, id):
    """
        Génère la courbe CP d'une activité donnée
        Note : Vue obsolète
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    activity = Activity.objects.get(id = id)
    if not activity.cp_curve:
        raise Http404

    cp_curve = pickle.loads(base64.b64decode(activity.cp_curve))

    f = plt.figure(figsize=(12, 6))

    plt.xlabel('Durée (s)')
    plt.plot(np.arange(1, len(cp_curve)), cp_curve[:-1])
    plt.semilogx()
    x = [1,5,15,30,60,120,180,300,600,1200,1800,3600,7200,10800,18000]
    labels = ['1s', '5s', '15s', '30s', '1m', '2m', '3m', '5m', '10m', '20m', '30m', '1h', '2h', '3h', '5h']
    plt.xticks(x, labels)

    canvas = FigureCanvasAgg(f)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    matplotlib.pyplot.close(f)
    return response

def graph_time(request, id):
    """
        Génère un graphique avec l'évolution des métriques
        en fonction du temps.
        Note : vue obsolète
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    streams = Stream.objects.filter(activity__id = id)
    if streams.count() == 0:
        raise Http404

    # Get time stream
    s = streams.get(metric='time')
    np_bytes = base64.b64decode(s.data)
    time = pickle.loads(np_bytes)
    # Check if time is sparse (juste pour info)
    sparse = ((time+time[::-1]) != time[0]+time[-1]).any()

    f, ax1 = plt.subplots(figsize=(18, 5))

    ax1.set_label('temps (s)')
    if streams.filter(metric='altitude').exists():
        color = 'tab:blue'
        ax1.set_ylabel('altitude (m)', color=color)
        altitude = pickle.loads(base64.b64decode(streams.get(metric='altitude').data))
        ax1.plot(time, altitude, color=color)
        ax1.tick_params(axis='y', labelcolor=color)
    if streams.filter(metric='watts').exists():
        color = 'tab:red'
        ax2 = ax1.twinx()
        ax2.set_ylabel('puissance (W)', color=color)
        watts = pickle.loads(base64.b64decode(streams.get(metric='watts').data))
        ax2.plot(time, watts, color=color)
        ax2.tick_params(axis='y', labelcolor=color)

    canvas = FigureCanvasAgg(f)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    matplotlib.pyplot.close(f)
    return response

def activity_details(request, id):
    """Affiche les détails d'une activité"""

    activity = Activity.objects.get(id=id)
    if activity.verify_deleted():
        print("Activity was deleted on Strava")
        # TODO Must return an error or a warning
        # return render(request, 'centcols/activity_details.html', locals())
        activity.delete()
        return HttpResponse("Activity does not exist on Strava and is now deleted on current app")

    if activity.gear_id and activity.gear.raw_data == {}:
        activity.sync_gear_details()

    if not activity.detailsHandled:
        activity.scan()

    if not activity.colsHandled:
        activity.do_check_passes()

    if not activity.streamsHandled:
        activity.get_streams()

    if not activity.tilesHandled:
        activity.do_check_tiles(zoom=14)

    if not activity.cp_curveHandled:
        activity.compute_cp_curve()

    streams = Stream.objects.filter(activity=activity)

    hasPower = False
    hasAltitude = False
    for stream in streams:
        if stream.metric == 'watts':
            hasPower = True
        if stream.metric == 'altitude':
            hasAltitude = True

    # Cols franchis
    cols = activity.climbs.all()

    # Number of visited tiles
    n_visited_tiles = activity.visited_tiles.count()

    # D+ max en 1h
    if hasAltitude:
        # Get time and altitude array
        time = pickle.loads(base64.b64decode(streams.get(metric='time').data))
        altitude = pickle.loads(base64.b64decode(streams.get(metric='altitude').data))
        if len(time)!=0 :
            # Check if time is sparse (juste pour info)
            sparse = ((time+time[::-1]) != time[0]+time[-1]).any()
            # Compute elevation gain
            elevation_gain = np.zeros_like(time, dtype=float)
            #elevation_gain[1:] = altitude[1:]-altitude[:-1]
            for i in range(1, len(altitude)):
                if altitude[i] > altitude[i-1]:
                    elevation_gain[i] = altitude[i] - altitude[i-1]

            # Create a dense elevation gain array
            el_gain_dense = np.zeros(time[-1]+1, dtype=float)
            el_gain_dense[time[:]] = elevation_gain[:]

            max_1h_climb = np.max(np.convolve(el_gain_dense, np.ones(3600), 'valid'))

    return render(request, 'centcols/activity_details.html', locals())

def gear_details(request, id):
    """Display details of a gear"""

    gear = Gear.objects.get(id=id)

    # If request id POST, handle form
    if request.method == 'POST':
        form = AddGearMaintenance(request.POST)
        if form.is_valid():
            add_maintenance(form, gear)
            return redirect(reverse('gear_details', args=[id]))
    else:
        # If request is GET, print empty form
        form = AddGearMaintenance()



    if form.is_valid():
        add_maintenance(form, gear)

    services = GearMaintenanceManager.objects.filter(gear=gear).order_by('-date')

    result = Activity.objects.filter(gear=gear).aggregate(
        total_distance=Sum('distance'),
        total_moving_time=Sum('moving_time')
    )

    distance = result['total_distance'] or 0
    moving_time = result['total_moving_time'] or 0




    return render(request, 'centcols/gear_details.html', {'gear': gear,
                                                          'distance': distance,
                                                          'moving_time': moving_time,
                                                          'services': services,
                                                          'form': form})


def sync_maintenance_view(request, maint_id):
    """
    Vue pour synchroniser les données de maintenance.
    """
    try:
        service = get_object_or_404(GearMaintenanceManager, id=maint_id)
        print(service)
        result = Activity.objects.filter(gear=service.gear, startDate__lte=service.date).aggregate(
            distance=Sum('distance'),
            time=Sum('moving_time')
        )
        service.gear_distance = result['distance'] or 0
        service.gear_time = result['time'] or 0
        service.save()
        messages.success(request, f"Maintenance {maint_id} synchronisée avec succès.")
    except Exception as e:
        # TODO : faut-il utiliser message ou logger ?
        print('pouet !')
        messages.error(request, f"Erreur lors de la synchronisation : {e}")

    # print(service.gear.id)
    return redirect(reverse('gear_details', args=[service.gear.id]))

def maintenance(request, action):
    """Différentes options de maintenance"""
    if action==1:
        # Récup' détail des activités Ride, VirtualRide et non commute
        activities = Activity.objects.filter(Q(Type="Ride")|Q(Type="VirtualRide"), commute=False, detailsHandled=False).order_by('startDate')
        for activity in activities:
            if not activity.detailsHandled:
                print(activity.name)
                if not activity.scan():
                    # break
                    continue       # Permet d'éviter un arrêt lorsque l'activité n'a pas de polyline (cas des activité HT)
                    # TODO Tester aussi indoor, trainer, manual, etc.
    if action==2:
        # Récup' streams des activités Ride et non commute
        activities = Activity.objects.filter(Q(Type="Ride")|Q(Type="VirtualRide"), commute=False,streamsHandled=False).order_by('startDate')
        for activity in activities:
            if not activity.streamsHandled:
                print(activity.name)
                if not activity.get_streams():
                    break
    if action==3:
        # Supprime tous les cols des activités Ride
        activities = Activity.objects.filter(Type="Ride", commute=False,colsHandled=True).order_by('startDate')
        for activity in activities:
            cols = activity.climbs.all()
            for col in cols:
                activity.climbs.remove(col)
            activity.colsHandled = False
            activity.save()

        # Suppression des cols
        Col.objects.all().delete()

        # Suppression des imports OSM
        OSMImport.objects.all().delete()

    if action==4:
        # Scanne les activités avec détails pour trouver les cols
        activities = Activity.objects.filter(Type="Ride", commute=False,detailsHandled=True,colsHandled=False).order_by('startDate')
        for activity in activities:
            activity.do_check_passes()

    if action==5:
        # Calcul des courbes CP des activités Ride et VirtualRide
        activities = Activity.objects.filter(Q(Type="Ride")|Q(Type="VirtualRide"), commute=False, streamsHandled=True, cp_curveHandled=False).order_by('startDate')
        for activity in activities:
            print(f'{activity.name =}')
            activity.compute_cp_curve()

    if action==6:
        # Cherche les tuiles des activités Ride
        activities = Activity.objects.filter(Type="Ride", tilesHandled=False, detailsHandled=True).order_by('startDate')
        #activities = Activity.objects.filter(Type="Ride", detailsHandled=True).order_by('startDate')
        for activity in activities:
            print(activity.name)
            activity.do_check_tiles(zoom=14)

    if action==7:
        # Supprime toutes les tuiles des activités Ride
        activities = Activity.objects.filter(Type="Ride", commute=False,tilesHandled=True).order_by('startDate')
        for activity in activities:
            tiles = activity.visited_tiles.all()
            for tile in tiles:
                activity.visited_tiles.remove(tile)
            activity.tilesHandled = False
            activity.save()

        # Suppression des cols
        Tile.objects.all().delete()

    if action==8:
        from django.db.models import Max, Min
        # Recherche et mise à jour des activités modifiées
        before = Activity.objects.aggregate(Max('startDate'))
        # after = Activity.objects.aggregate(Min('startDate'))
        import ciso8601
        import time
        ts = ciso8601.parse_datetime("20260101")
        # to get time in seconds:
        after = time.mktime(ts.timetuple())

        #TODO coder une action à part
        from services.strava_service import StravaService
        service = StravaService()

        page = 0
        per_page = 200
        max_page = 1000
        modified_activities_id = []

        while True:
            page = page + 1
            if page > max_page:
                break
            activities = service.get_activities(page=page, per_page=per_page,
                                                before=before['startDate__max'].timestamp(),
                                                after=after)
            if len(activities) == 0:
                print('no activity returned')
                break
            print(len(activities), "activities returned from Strava")

            #TODO Faire une méthode à part dans la classe Activity
            for activity_data in activities:
                #print(activity['name'])
                # Compare with activity in database
                q = Activity.objects.filter(stravaId=activity_data['id'])
                if q.exists():
                    a = q[0]
                    modified = a.check_modified(activity_data)
                    if modified:
                        logger.info("Activity %s (%s) has been modified.", activity_data['id'], activity_data['name'])
                        modified_activities_id.append(activity_data['id'])
                else:
                    print("Activity ",activity_data['id']," is not in database ???")


            print(modified_activities_id)
            print(len(modified_activities_id))
            for id in modified_activities_id:
                q = Activity.objects.filter(stravaId=id)
                if q.exists():
                    print("Mise à jour...")
                    a = q[0]
                    a.update()
            modified_activities_id = []

    if action==9:
        # Récup' Des matériels
        activities = Activity.objects.order_by('startDate')
        for activity in activities:
            if activity.gear_id and activity.gear.raw_data == {}:
                activity.sync_gear_details()


    return render(request, 'centcols/maintenance.html', locals())


def graph_test(request):
    """Test generation of an image"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    #Activity.objects.filter(Type='Ride').count()
    #Activity.objects.filter(Type='Run').count()
    # Tous les types
    activities = Activity.objects.order_by('Type').values('Type').distinct()
    count = []
    types = []
    print(activities)
    for activity in activities:
        types.append(activity['Type'])
        count.append(Activity.objects.filter(Type=activity['Type']).count())




    #plt.xkcd()
    f = plt.figure()

    wedges, texts = plt.pie(count)
    plt.legend(wedges, types, loc="upper center",bbox_to_anchor=(-0.4, 0, 0.5, 1))

    canvas = FigureCanvasAgg(f)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    matplotlib.pyplot.close(f)
    return response


def indicators(request):
    """Affichages de statistiques"""
    activities = Activity.objects.all()
    count=len(activities)
    distance = activities.aggregate(Sum('distance'))['distance__sum']
    moving_time = activities.aggregate(Sum('moving_time'))['moving_time__sum']
    elapsed_time = activities.aggregate(Sum('elapsed_time'))['elapsed_time__sum']

    # Compute Eddington score
    eddington = 0
    while True:
        if activities.annotate(day=TruncDay('startDate')).values('day').annotate(d=Sum('distance')).filter(d__gt=eddington*1000).count() < eddington:
            break
        eddington += 1

    # Compute 2025 indicators
    start_date = timezone.make_aware(datetime(2025, 1, 1))
    end_date = timezone.make_aware(datetime(2025, 12, 31))

    activities_2025 = Activity.objects.filter(startDate__gte=start_date,startDate__lte=end_date)
    total_distance_commute = activities_2025.filter(commute=True, Type="Ride").aggregate(Sum('distance'))['distance__sum']
    total_distance_notrainer = activities_2025.filter(trainer=False, Type="Ride").aggregate(Sum('distance'))['distance__sum']
    total_distance_notrainer_nocommute = activities_2025.filter(commute=False, trainer=False, Type="Ride").aggregate(Sum('distance'))['distance__sum']
    total_elevation_notrainer = activities_2025.filter(trainer=False, Type="Ride").aggregate(Sum('total_elevation_gain'))['total_elevation_gain__sum']
    total_time = activities_2025.filter(Q(Type="Ride")|Q(Type="VirtualRide")).aggregate(Sum('moving_time'))['moving_time__sum']
    total_time_notrainer = activities_2025.filter(trainer=False, Type="Ride").aggregate(Sum('moving_time'))['moving_time__sum']
    total_time_nocommute = activities_2025.filter(Q(commute=False, Type="Ride")|Q(Type="VirtualRide")).aggregate(Sum('moving_time'))['moving_time__sum']


    return render(request, 'centcols/indicators.html', {'count': count,
                                                        'distance': distance,
                                                        'moving_time': moving_time,
                                                        'elapsed_time': elapsed_time,
                                                        'eddington': eddington,
                                                        'total_distance_commute': total_distance_commute,
                                                        'total_distance_notrainer': total_distance_notrainer,
                                                        'total_distance_notrainer_nocommute': total_distance_notrainer_nocommute,
                                                        'total_elevation_notrainer': total_elevation_notrainer,
                                                        'total_time': total_time,
                                                        'total_time_notrainer': total_time_notrainer,
                                                        'total_time_nocommute': total_time_nocommute,
                                                        })

def activities_climbed(request, id_col):
    """Affichage des activités où un col donné a été franchi"""
    activities = Activity.objects.filter(climbs__id=id_col)
    return render(request, 'centcols/list_activities.html', {'activities': activities})

def climbed(request):
    """Affichage de tous les cols franchis"""
    # TODO trouver un meilleur filtre
    cols = Col.objects.filter(activity__name__contains='').order_by('-elevation').distinct()
    return render(request, 'centcols/list_climbed.html', {'cols': cols})



def import_strava(request):
    """
    Importe les activités depuis Strava en utilisant un formulaire
    permettant de définir une date de début et une date de fin
    """

    form = ImportStravaForm(request.POST or None)

    if form.is_valid():
        #TODO : ajouter des tests pour vérifier que la date est cohérente


        # TODO : vérifier l'heure ajoutée à la date
        before = datetime.combine(form.cleaned_data['endDate'],datetime.min.time()).timestamp()
        after = datetime.combine(form.cleaned_data['startDate'],datetime.min.time()).timestamp()

        count = retrieve_and_save_activities(before, after, scan=False)

        envoi = True
    # TODO la vue attend une liste des noms des activités importées
    return render(request, 'centcols/import_strava.html', locals())

def list_cols(request):
    """
    Affichage de tous les cols
    """
    cols = Col.objects.all().order_by('-elevation')
    return render(request, 'centcols/list_cols.html', {'cols': cols})

def list_activities(request):
    """
    Print activities, with pagination
    """

    # Get page size from GET parameters, default=100
    page_size = int(request.GET.get('page_size', 100))

    # Get filters
    activity_type = request.GET.get('type', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    # Get all actuvities, decreasing date
    activities_list = Activity.objects.order_by('-startDate')

    # set filters
    if activity_type:
        activities_list = activities_list.filter(Type=activity_type)
    if start_date:
        activities_list = activities_list.filter(startDate__gte=start_date)
    if end_date:
        activities_list = activities_list.filter(startDate__lte=end_date)

    paginator = Paginator(activities_list, page_size)

    # Get page number
    page = request.GET.get('page', 1)

    try:
        activities = paginator.page(page)
    except PageNotAnInteger:
        activities = paginator.page(1)
    except EmptyPage:
        activities = paginator.page(paginator.num_pages)


    return render(request, 'centcols/list_activities.html', {
        'activities': activities,
        'page_size': page_size,
        'activity_type': activity_type,
        'start_date': start_date,
        'end_date': end_date,
    })


def list_gears(request):
    """
    Display all gears
    """
    gears = Gear.objects.order_by('-distance')
    return render(request, 'centcols/list_gears.html', {'gears': gears})












def import_osm(request):
    """
    Importe les cols depuis OpenStreetMap en utilisant un formulaire
    permettant de définir une bouding box
    """
    form = ImportOSMForm(request.POST or None)

    if form.is_valid():
        retrieve_and_save_passes(form.cleaned_data['minLat'], form.cleaned_data['minLon'],
                                 form.cleaned_data['maxLat'], form.cleaned_data['maxLon'])
        envoi = True

    return render(request, 'centcols/import_osm.html', locals())




#def addition(request, nb1, nb2):
    #"""
    #Réalise une addition
    #"""
    #total = nb1+nb2
    #return render(request, 'centcols/addition.html', locals())

#def date_actuelle(request):
    #"""
    #Retourne la date actuelle
    #"""
    #return render(request, 'centcols/date.html', {'date': datetime.now()})

#def redir(request):
    #"""
    #Redirection
    #"""
    ##return redirect("https://lamcosplm.insa-lyon.fr")
    #return redirect(home)

#def list_cols_by_tag(request, tag):
    #"""
    #Vue qui affiche une liste de cols correspondant à un tag donné
    #"""
    #return HttpResponse(
        #"Liste de col pour le tag {0}".format(tag)
    #)

#def view_col(request, id_col):
    #"""
    #Vue qui affiche un col en fonction de son identifiant
    #Si l'id est supérieur à 100, on retourne une erreur 404
    #"""
    #if id_col > 100:
        #raise Http404

    #return HttpResponse(
        #"Affichage du col portant l'ID {0}".format(id_col)
    #)

#def home(request):
    #""" Exemple simple, html pas vraiment valide """
    #return HttpResponse("""
        #<h1>Bienvenue sur mon catalogue des cent cols</h1>
        #<p>En cours de création...</p>
    #""")

def home(request):
    """
    Vue de la page d'accueil
    """
    return render(request, 'centcols/accueil.html')
