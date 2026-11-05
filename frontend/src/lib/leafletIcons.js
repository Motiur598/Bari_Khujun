import L from 'leaflet'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

// Leaflet finds its default marker images through a path read from its CSS, which breaks once Vite fingerprints the
// files, so point the default icon at the bundled images. The app's own pins are divIcons; this covers any plain
// <Marker>. Imported by RentalMap.jsx, which every map component loads, so Leaflet stays out of the main bundle.
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({ iconRetinaUrl: markerIcon2x, iconUrl: markerIcon, shadowUrl: markerShadow })
