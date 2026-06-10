from django.urls import path
from . import views

urlpatterns = [
    path('', views.home),
    path('accueil', views.home),
    path('maj-osm', views.import_osm, name="import_osm"),
    path('maj-strava', views.import_strava, name="import_strava"),
    path('activities', views.list_activities, name="list_activities"),
    path('climbed', views.climbed, name="list_climbed"),
    path('gears', views.list_gears, name="list_gears"),
    path('activities_climbed/<int:id_col>', views.activities_climbed, name="activities_climbed"),
    path('indicators', views.indicators, name="indicators"),
    path('maintenance/', views.maintenance, name="maintenance"),
    path('maintenance/<str:action>/', views.maintenance, name="maintenance_action"),
    path('durability/', views.list_durability_indicators, name='list_durability_indicators'),
    path('durability/<int:id>/', views.durability_indicator_detail, name='durability_indicator_detail'),
    path('durability/<int:id>/delete/', views.delete_durability_indicator, name='delete_durability_indicator'),
    path('activity_details/<int:id>',views.activity_details, name="activity_details"),
    path('gear_detail/<int:id>', views.gear_details, name='gear_details'),
    path('sync_maintenance/<int:maint_id>/', views.sync_maintenance_view, name='sync_maintenance'),
    path('graph_time/<int:id>/', views.graph_time, name="graph_time"),
    path('graph_test/', views.graph_test, name="graph_test"),
    path('graph_test_json/', views.graph_test_json, name="graph_test_json"),
    path('graph_cp/<int:id>/', views.graph_cp, name="graph_cp"),
    path('sumtrack_json/<int:id>/', views.sumtrack_json, name="sumtrack_json"),
    path('track_json/<int:id>/', views.track_json, name="track_json"),
    path('visited_tiles_json/<int:id>/', views.visited_tiles_json, name="visited_tiles_json"),
    path('all_sumtrack_json/', views.all_sumtrack_json, name="all_sumtrack_json"),
    path('climbed_json/<int:id>/', views.climbed_json, name="climbed_json"),
    path('all_climbed_json/', views.all_climbed_json, name="all_climbed_json"),
    path('time_streams_json/<int:id>', views.time_streams_json, name='time_streams_json'),
    path('cp_curve_json/<int:id>', views.cp_curve_json, name='cp_curve_json'),
    path('cp_best_json/<int:startday>/<int:startmonth>/<int:startyear>/<int:endday>/<int:endmonth>/<int:endyear>', views.cp_best_json, name='cp_best_json'),
    #path('col/<int:id_col>', views.view_col, name='afficher_col'),
    #path('col/<str:tag>', views.list_cols_by_tag),
    #path('red', views.redir),
    #path('date', views.date_actuelle),
    #path('addition/<int:nb1>/<int:nb2>', views.addition),
    #path('importosm/<str:blLat>/<str:blLon>/<str:trLat>/<str:trLon>', views.import_osm),
    #path('import_osm', views.import_osm2, name='import_osm_form'),
    #path('import_strava/<int:startday>/<int:startmonth>/<int:startyear>/<int:endday>/<int:endmonth>/<int:endyear>/', views.import_strava),
    #path('cols', views.list_cols),
    #path('activities', views.list_activities),
]
# Pour importosm, mettre plutôt une expression régulère pour tester le type de valeur



# Autre façon d'écrire la même chose avec des expression régulères
# Le cas avec deux paramètres ne passe pas

#urlpatterns = [
#    re_path(r'^accueil', views.home),
#    re_path(r'^col/(?P<id_col>.+)', views.view_col),
#    re_path(r'^cols/(?P<tag>.+)', views.list_cols_by_tag),
#    re_path(r'^cols/(?P<elevation>\d{4})/(?P<category>\d{1})', views.list_cols),
#]
