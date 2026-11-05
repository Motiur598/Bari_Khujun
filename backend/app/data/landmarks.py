"""Common commute destinations in Dhaka for the proximity filter.

Coordinates are approximate (main gate / central intersection) and good enough for radius search.
"""

LANDMARKS = [
    # Universities
    {"id": "du", "name": "University of Dhaka", "kind": "UNIVERSITY", "area": "Shahbag", "lat": 23.7340, "lng": 90.3928},
    {"id": "buet", "name": "BUET", "kind": "UNIVERSITY", "area": "Palashi", "lat": 23.7265, "lng": 90.3925},
    {"id": "dmc", "name": "Dhaka Medical College", "kind": "UNIVERSITY", "area": "Bakshibazar", "lat": 23.7258, "lng": 90.3976},
    {"id": "jnu", "name": "Jagannath University", "kind": "UNIVERSITY", "area": "Sadarghat", "lat": 23.7085, "lng": 90.4113},
    {"id": "nsu", "name": "North South University", "kind": "UNIVERSITY", "area": "Bashundhara", "lat": 23.8151, "lng": 90.4255},
    {"id": "iub", "name": "Independent University, Bangladesh", "kind": "UNIVERSITY", "area": "Bashundhara", "lat": 23.8156, "lng": 90.4279},
    {"id": "aiub", "name": "AIUB", "kind": "UNIVERSITY", "area": "Kuratoli", "lat": 23.8223, "lng": 90.4276},
    {"id": "bracu", "name": "BRAC University", "kind": "UNIVERSITY", "area": "Merul Badda", "lat": 23.7730, "lng": 90.4250},
    {"id": "ewu", "name": "East West University", "kind": "UNIVERSITY", "area": "Aftabnagar", "lat": 23.7685, "lng": 90.4255},
    # Office hubs
    {"id": "gulshan-1", "name": "Gulshan 1 Circle", "kind": "OFFICE_HUB", "area": "Gulshan", "lat": 23.7806, "lng": 90.4167},
    {"id": "gulshan-2", "name": "Gulshan 2 Circle", "kind": "OFFICE_HUB", "area": "Gulshan", "lat": 23.7946, "lng": 90.4143},
    {"id": "banani", "name": "Banani Road 11", "kind": "OFFICE_HUB", "area": "Banani", "lat": 23.7937, "lng": 90.4043},
    {"id": "motijheel", "name": "Motijheel C/A", "kind": "OFFICE_HUB", "area": "Motijheel", "lat": 23.7330, "lng": 90.4172},
    {"id": "kawran-bazar", "name": "Kawran Bazar", "kind": "OFFICE_HUB", "area": "Tejgaon", "lat": 23.7509, "lng": 90.3935},
    {"id": "mohakhali", "name": "Mohakhali", "kind": "OFFICE_HUB", "area": "Mohakhali", "lat": 23.7779, "lng": 90.4056},
    {"id": "dhanmondi-27", "name": "Dhanmondi 27", "kind": "OFFICE_HUB", "area": "Dhanmondi", "lat": 23.7561, "lng": 90.3740},
    {"id": "mirpur-10", "name": "Mirpur 10 Circle", "kind": "OFFICE_HUB", "area": "Mirpur", "lat": 23.8069, "lng": 90.3687},
    {"id": "uttara", "name": "Uttara (Jasimuddin)", "kind": "OFFICE_HUB", "area": "Uttara", "lat": 23.8616, "lng": 90.4003},
]

LANDMARKS_BY_ID = {landmark["id"]: landmark for landmark in LANDMARKS}
