class SourcesMap {

    constructor(mapSources) {
        // Render the map in this element.
        let mapElement = document.getElementById('map');

        // This center is chosen so that the relatively empty latitude
        // range between US west coast and Hawaii is at the edge of the
        // map.
        let center = [12.0, 40.0];
        // Zoom level 2 shows exactly one Earth when the map is
        // displayed at around 1024 x 1024 pixels.
        //
        // Ideally we'd use a fractional zoom level, so that we can make
        // the map show exactly one Earth without having to either
        // 1) match 1024px width exactly or 2) CSS-scale the map element.
        // However, Leaflet.markercluster seems to make some markers
        // disappear with fractional zoom levels.
        // https://jsfiddle.net/j1ew93yo/2/
        // https://github.com/Leaflet/Leaflet.markercluster/pull/887
        let initialZoom = 2;

        // Create Leaflet map.
        this.map = L.map(mapElement, {
            // How much the zoom level changes from the +/- buttons or
            // a double-click.
            zoomDelta: 1.0,
            // The zoom level snaps to multiples of this value if it's
            // above 0. If it is 0, then the zoom level can be an
            // arbitrary fractional value.
            zoomSnap: 0,
            // After panning far enough, make the map 'warp' back to the
            // initial 'copy' of the world.
            // Additionally, we will duplicate each marker twice on the
            // map. These two tricks will ensure that a marker is never
            // missing from view.
            worldCopyJump: true,
        }).setView(center, initialZoom);

        // Add OpenStreetMap tile layer to the map.
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            // Don't set this too low, or people could see Earth
            // wrapping around multiple times on the map.
            minZoom: initialZoom,
            // Don't set this too high, so people don't get lost after
            // clicking a bunched-together map cluster, and also because
            // OpenStreetMap gets more concerned about usage when
            // serving tiles at higher zoom levels.
            maxZoom: 9,
            attribution: 'Map data from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(this.map);

        // Define marker icons.
        let aspectRatio = 50/82;
        let iconSizes = {
            // Original aspect ratio is (50, 82)
            1: new L.Point(22, 22/aspectRatio),
            2: new L.Point(26, 26/aspectRatio),
            3: new L.Point(30, 30/aspectRatio),
        };
        let iconStyles = {
            public: 'public-source',
            private: 'private-source',
        };
        // 2-D hash, indexed by size (1/2/3), then by type (public/private)
        let icons = {}
        for (let [sizeKey, size] of Object.entries(iconSizes)) {
            icons[sizeKey] = {}
            for (let [styleKey, styleClass] of Object.entries(iconStyles)) {
                let iconClass = L.Icon.Default.extend({
                    options: {
                        iconSize: size,
                        className: styleClass,
                    },
                });
                icons[sizeKey][styleKey] = new iconClass();
            }
        }

        // Place markers.

        let markers = L.markerClusterGroup();
        this.popup = L.popup({
            maxWidth: 550,
        });

        for (let source of mapSources) {
            let latitude = Number(source['latitude']);
            let longitude = Number(source['longitude']);
            if (isNaN(latitude) || isNaN(longitude)) {
                continue;
            }

            // 'Main' marker.
            let coordinateSets = [[latitude, longitude]];
            // Extra marker to cover panning right until the
            // worldCopyJump kicks in. The 20.0 margin is to allow markers
            // near the edge to be grouped into clusters with stuff
            // slightly beyond the edge.
            if (longitude < 20.0) {
                coordinateSets.push([latitude, longitude + 360.0]);
            }
            // Extra marker to cover panning left until the
            // worldCopyJump kicks in.
            if (longitude > -20.0) {
                coordinateSets.push([latitude, longitude - 360.0]);
            }

            for (let coordinates of coordinateSets) {
                let marker = L.marker(
                    coordinates,
                    {icon: icons[source['size']][source['type']]},
                );

                // Click-handler for the marker.
                marker.addEventListener('click', (event) => {
                    this.showSourceDetail(
                        source['detailBoxUrl'], coordinates);
                })

                markers.addLayer(marker);
            }
        }

        this.map.addLayer(markers);
    }

    showSourceDetail(detailBoxUrl, coordinates) {
        this.popup
        .setLatLng(coordinates)
        .setContent("Getting source info...")
        .openOn(this.map);

        util.fetch(
            detailBoxUrl,
            {},
            (response) => {
                // Add the source-detail HTML to the map's popup
                let detailBoxContainer = document.createElement('div');
                detailBoxContainer.insertAdjacentHTML(
                    'afterbegin', response['detailBoxHtml']);
                this.popup.setContent(detailBoxContainer);
            }
        )
    }
}
