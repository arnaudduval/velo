/**
 * Shared Leaflet setup: tile layer selector + fullscreen button.
 * Call initMapControls(map) at the start of any main_map_init callback.
 */
function initMapControls(map) {
    map.eachLayer(function(layer) {
        if (layer instanceof L.TileLayer) { map.removeLayer(layer); }
    });

    var osmLayer = L.tileLayer(
        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 19 }
    ).addTo(map);
    var topoLayer = L.tileLayer(
        'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        { attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | Style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>', maxZoom: 17 }
    );
    var cartoLayer = L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
        { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>', subdomains: 'abcd', maxZoom: 19 }
    );
    L.control.layers({ 'OSM': osmLayer, 'Topo': topoLayer, 'CartoDB': cartoLayer }).addTo(map);

    var FullscreenControl = L.Control.extend({
        options: { position: 'topleft' },
        onAdd: function(m) {
            var btn = L.DomUtil.create('a', 'leaflet-bar leaflet-control leaflet-control-fullscreen');
            btn.href = '#';
            btn.title = 'Plein écran';
            btn.innerHTML = '&#x26F6;';
            btn.style.cssText = 'font-size:16px;line-height:30px;text-align:center;display:block;width:30px;height:30px;text-decoration:none;color:#333;background-color:#fff;cursor:pointer;';
            L.DomEvent.on(btn, 'click', L.DomEvent.preventDefault);
            L.DomEvent.on(btn, 'click', function() {
                var el = m.getContainer();
                if (!document.fullscreenElement) {
                    el.requestFullscreen();
                } else {
                    document.exitFullscreen();
                }
            });
            document.addEventListener('fullscreenchange', function() {
                btn.innerHTML = document.fullscreenElement ? '&#x2715;' : '&#x26F6;';
                setTimeout(function() { m.invalidateSize(); }, 100);
            });
            return btn;
        }
    });
    new FullscreenControl().addTo(map);
}
