import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models.db_models import Station
from app.utils import slugify

STATIONS = [
    ("Bandra Kurla Complex, Mumbai - IITM", "IITM", 19.053536, 72.84643),
    ("Bandra Kurla Complex, Mumbai - MPCB", "MPCB", 19.065931, 72.862131),
    ("Borivali East, Mumbai - IITM", "IITM", 19.23241, 72.86895),
    ("Byculla, Mumbai - BMC", "BMC", 18.9767, 72.838),
    ("Chakala-Andheri East, Mumbai - IITM", "IITM", 19.11074, 72.86084),
    ("Chembur, Mumbai - MPCB", "MPCB", 19.0364585, 72.8954371),
    ("Chhatrapati Shivaji Intl. Airport (T2), Mumbai - MPCB", "MPCB", 19.10078, 72.87462),
    ("Deonar, Mumbai - IITM", "IITM", 19.04946, 72.923),
    ("Ghatkopar, Mumbai - BMC", "BMC", 19.083694, 72.920967),
    ("Kandivali West, Mumbai - BMC", "BMC", 19.215859, 72.831718),
    ("Kherwadi_Bandra East, Mumbai - MPCB", "MPCB", 19.0632143, 72.8456324),
    ("Khindipada-Bhandup West, Mumbai - IITM", "IITM", 19.1653323, 72.922099),
    ("Kurla, Mumbai - MPCB", "MPCB", 19.0863, 72.8888),
    ("Malad West, Mumbai - IITM", "IITM", 19.19709, 72.82204),
    ("Mazgaon, Mumbai - IITM", "IITM", 18.96702, 72.84214),
    ("Mindspace-Malad West, Mumbai - MPCB", "MPCB", 19.1878657, 72.8304069),
    ("Mulund West, Mumbai - MPCB", "MPCB", 19.175, 72.9419),
    ("Navy Nagar-Colaba, Mumbai - IITM", "IITM", 18.897756, 72.81332),
    ("Powai, Mumbai - MPCB", "MPCB", 19.1375, 72.915056),
    ("Sewri, Mumbai - BMC", "BMC", 19.000084, 72.85673),
    ("Shivaji Nagar, Mumbai - BMC", "BMC", 19.060498, 72.923356),
    ("Siddharth Nagar-Worli, Mumbai - IITM", "IITM", 19.000083, 72.813993),
    ("Sion, Mumbai - MPCB", "MPCB", 19.047, 72.8746),
    ("Worli, Mumbai - MPCB", "MPCB", 18.9936162, 72.8128113),
        ("Borivali East, Mumbai - MPCB", "MPCB", 19.23241, 72.86895),
]

def main():
    db = SessionLocal()
    created, skipped= 0 , 0

    for name, agency, lat, lng in STATIONS:
        station_id = slugify(name)
        existing = db.query(Station).filter_by(station_id=station_id).first()
        if existing:
            skipped += 1
            continue

        station = Station(
            station_id = station_id,
            name = name,
            agency = agency,
            latitude = lat,
            longitude = lng
        )
        db.add(station)
        created += 1

    db.commit()
    db.close()
    print(f"Created {created} new station(s), skipped {skipped} already-existing.")
    print(f"Total stations should now be: {created + skipped if skipped else created}")

if __name__ == "__main__":
    main()