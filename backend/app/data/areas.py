"""Popular Dhaka areas for the "Where are you shifting?" picker.

`lat`/`lng` is roughly the middle of the area and `radius_km` its rough extent. The listing location picker snaps a
pin inside one of these circles to the area's name, so owners and tenants use the same names (OpenStreetMap's own
names for Dhaka neighbourhoods are inconsistent). Search matches names as whole words, so "Mirpur" also finds
"Mirpur 10" and "Uttara" finds "Uttara Sector 7".
"""

POPULAR_AREAS = [
    {"name": "Aftabnagar", "lat": 23.7670, "lng": 90.4420, "radius_km": 0.8},
    {"name": "Azimpur", "lat": 23.7272, "lng": 90.3860, "radius_km": 0.8},
    {"name": "Badda", "lat": 23.7790, "lng": 90.4260, "radius_km": 1.2},
    {"name": "Banani", "lat": 23.7937, "lng": 90.4043, "radius_km": 1.0},
    {"name": "Baridhara", "lat": 23.8005, "lng": 90.4215, "radius_km": 0.8},
    {"name": "Bashundhara R/A", "lat": 23.8180, "lng": 90.4380, "radius_km": 1.8},
    {"name": "Dhanmondi", "lat": 23.7461, "lng": 90.3742, "radius_km": 1.3},
    {"name": "Farmgate", "lat": 23.7577, "lng": 90.3897, "radius_km": 0.6},
    {"name": "Gulshan", "lat": 23.7925, "lng": 90.4150, "radius_km": 1.3},
    {"name": "Khilgaon", "lat": 23.7517, "lng": 90.4250, "radius_km": 1.0},
    {"name": "Lalmatia", "lat": 23.7558, "lng": 90.3665, "radius_km": 0.6},
    {"name": "Mirpur", "lat": 23.8069, "lng": 90.3654, "radius_km": 3.0},
    {"name": "Mohakhali", "lat": 23.7780, "lng": 90.3990, "radius_km": 0.9},
    {"name": "Mohammadpur", "lat": 23.7620, "lng": 90.3580, "radius_km": 1.4},
    {"name": "Motijheel", "lat": 23.7330, "lng": 90.4172, "radius_km": 1.0},
    {"name": "Niketan", "lat": 23.7730, "lng": 90.4110, "radius_km": 0.5},
    {"name": "Rampura", "lat": 23.7612, "lng": 90.4210, "radius_km": 1.0},
    {"name": "Tejgaon", "lat": 23.7600, "lng": 90.3950, "radius_km": 1.2},
    {"name": "Uttara", "lat": 23.8700, "lng": 90.3950, "radius_km": 3.0},
]
