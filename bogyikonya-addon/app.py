import json
import os
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory

# --- INGRESS BEÁLLÍTÁS ---
# A Home Assistant Supervisor környezeti változója, ami elvileg a teljes útvonalat adná (de hibásan csak '/' ad)
INGRESS_ENTRY_POINT = os.environ.get('SUPERVISOR_INGRESS_ENTRY', '/') 
print(f"[DEBUG] Ingress entry point: {INGRESS_ENTRY_POINT}")
# Biztosítjuk, hogy az útvonal '/' -re végződjön az útvonal-illesztéshez
if not INGRESS_ENTRY_POINT.endswith("/"):
    INGRESS_ENTRY_POINT += "/"

app = Flask(__name__)
DATA_FILE = "/data/app_data.json"

# --- JSON fájlkezelő és Segédfüggvények ---

def load_data():
    """Adatok betöltése a perzisztens JSON fájlból."""
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except Exception:
        # Ha a fájl nem létezik, vagy üres, inicializáljuk az adatokat.
        data = {}
    default_data = {"preparedMeals": [], "pantry": [], "shoppingList": [], "recipes": []}
    for key in default_data:
        if key not in data:
            data[key] = default_data[key]
    return data

def save_data(data):
    """Adatok mentése a perzisztens JSON fájlba."""
    try:
        with open(DATA_FILE, 'w') as f:
            # A `json.dump` használata biztosítja a JSON formátumot
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[ERROR] Mentési hiba: {e}")
        return False

def to_local_format(item):
    """Eltávolítja a Firestore-specifikus mezőket (ha lennének) és biztosítja a helyes dátumformátumot."""
    # Mivel ez egy lokális API, itt nincs szükség bonyolult konverzióra, csak visszatérünk az eredeti elemmel.
    return item

def generate_id():
    """Egyedi azonosító generálása az időbélyeg alapján."""
    return str(int(time.time() * 1000))

def update_item_timestamps(item):
    """Létrehozási időbélyeg hozzáadása, ha hiányzik."""
    now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    if 'createdAt' not in item:
        item['createdAt'] = now_iso
    return item

# --- ÚTVONALAK (INGRESS HELYESEN KEZELVE) ---

# 1. INDEX FÁJL KISZOLGÁLÁSA
@app.route(INGRESS_ENTRY_POINT)
def serve_index():
    """Főoldal kiszolgálása a www mappából, injektálva a JS-be a base path-t."""
    try:
        # A Home Assistant Ingress útvonalának injektálása a kliens oldali JS-nek
        with open(os.path.join('www', 'index.html'), 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Létrehozzuk a globális JS változót (tartalmazhatja a hibás '/' értéket is!)
        # Bár az index.html JS-e már okosan kezeli a window.location.pathname-t, 
        # ez a megoldás egy általános biztonsági réteg lehet.
        js_injection = f'<script>window.HASS_API_BASE_PATH = "{INGRESS_ENTRY_POINT}";</script>'
        
        # Beillesztjük a </head> elé
        modified_html = html_content.replace('</head>', js_injection + '</head>')
        
        return modified_html
        
    except FileNotFoundError:
        return "Hiba: index.html fájl nem található a 'www' mappában.", 404

# 2. STATIKUS FÁJLOK KISZOLGÁLÁSA
# Ez kezeli a /.../ingress/style.css és a /.../ingress/app.js hívásokat
@app.route(f'{INGRESS_ENTRY_POINT}<path:filename>')
def serve_static(filename):
    """Statikus fájlok (JS, CSS, képek) kiszolgálása a www mappából az Ingress prefixet használva."""
    return send_from_directory('www', filename)

# 3. API VÉGPONTOK (INGRESS HELYESEN BEÉPÍTVE)

# GET route (Adatok lekérése)
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>', methods=['GET'])
def get_collection(collection_name):
    data = load_data()
    collection = data.get(collection_name, [])

    formatted_collection = [to_local_format(item) for item in collection]
    return jsonify(formatted_collection)

# POST route (Új elem hozzáadása)
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>', methods=['POST'])
def add_item(collection_name):
    new_item = request.json
    new_item = update_item_timestamps(new_item)
    new_item['id'] = generate_id()

    data = load_data()
    data.get(collection_name, []).append(new_item)

    if save_data(data):
        return jsonify({'id': new_item['id'], 'success': True}), 201
    else:
        return jsonify({'error': 'Mentési hiba'}), 500

# PUT route (Elem frissítése - ÚJ)
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>', methods=['PUT'])
def update_item(collection_name, item_id):
    updated_data = request.json
    data = load_data()
    collection = data.get(collection_name)

    if collection is None:
        return jsonify({'error': f'A gyűjtemény ({collection_name}) nem létezik'}), 400

    found = False
    for i, item in enumerate(collection):
        if item.get('id') == item_id:
            # Frissítjük az összes mezőt a bejövő adatokkal
            # Megtartjuk a 'createdAt' időbélyeget, de frissíthetjük a többit.
            
            # Ne engedjük, hogy a kliens felülírja a létrehozás idejét
            if 'createdAt' in updated_data:
                del updated_data['createdAt']
                
            # Cseréljük ki a régi elemet a frissített adatokkal, 
            # de garantáljuk az ID és a createdAt megmaradását
            collection[i].update(updated_data)
            collection[i]['id'] = item_id # Biztos, ami biztos
            
            found = True
            break

    if found:
        if save_data(data):
            return jsonify({'success': True, 'id': item_id}), 200
        else:
            return jsonify({'error': 'Mentési hiba'}), 500
    else:
        return jsonify({'error': 'Elem nem található'}), 404

# DELETE route (Elem törlése)
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>', methods=['DELETE'])
def delete_item(collection_name, item_id):
    data = load_data()
    collection = data.get(collection_name, [])

    initial_length = len(collection)
    # Csak azokat az elemeket hagyjuk meg, amiknek az ID-je NEM egyezik meg a törlendővel
    data[collection_name] = [item for item in collection if item.get('id') != item_id]

    if len(data[collection_name]) < initial_length:
        if save_data(data):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Mentési hiba'}), 500
    else:
        return jsonify({'error': 'Elem nem található'}), 404

if __name__ == '__main__':
    # Home Assistant add-on környezetben futtatva a megadott porton
    app.run(host='0.0.0.0', port=8099)
