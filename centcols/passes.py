from .models import OSMImport, Col
from stravatools import osmtools

def retrieve_and_save_passes(min_lat, min_lon, max_lat, max_lon):
    """
        Retrieve passes from OSM
    """
    cols = osmtools.get_pass_from_osm([[min_lat,min_lon],[max_lat,max_lon]])
    count = 0 
    imported = []
    if len(cols) != 0:
        for col in cols:
        # Verify if pass already exists
            if( not Col.objects.filter(osmId=col['osmid'])):
                # Only deal with passes with altitude and name
                if ('name' in col) and ('ele' in col):
                    c = Col(name = col['name'],
                    elevation = col['ele'],
                    latitude = col['lat'],
                    longitude = col['lon'],
                    osmId = col['osmid'])
                    c.save()
                    imported.append(c)
                    count=count+1
        print(count)
    imp = OSMImport(bboxBotLeftLat=min_lat,
                    bboxBotLeftLon=min_lon,
                    bboxTopRightLat=max_lat,
                    bboxTopRightLon=max_lon)
    imp.save()
