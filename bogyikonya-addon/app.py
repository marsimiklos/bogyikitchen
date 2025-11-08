import json
import os
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory

# --- INGRESS BEÁLLÍTÁS ---
# A Home Assistant Supervisor megadja a SUPERVISOR_INGRESS_ENTRY-t (pl. /api/hassio_addons/bogyikonya/ingress/)
INGRESS_ENTRY_POINT = os.environ.get('SUPERVISOR_INGRESS_URL', '/') # Ez a változó / -re végződik

# A korábbi INGRESS_PREFIX logikát elhagyjuk, mert felesleges volt és hibát okozott.

app = Flask(__name__)
DATA_FILE = "/data/app_data.json"

# --- JSON fájlkezelő és Segédfüggvények (NEM VÁLTOZNAK) ---

def load_data():
    """Adatok betöltése a perzisztens JSON fájlból."""
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        default_data = {"preparedMeals": [], "pantry": [], "shoppingList": [], "recipes": []}
        for key in default_data:
            if key not in data:
                data[key] = default_data[key]
        return data
    except Exception as e:
        print(f"Hiba az adat betöltésekor: {e}")
        return {"preparedMeals": [], "pantry": [], "shoppingList": [], "recipes": []}

def save_data(data):
    """Adatok mentése a perzisztens JSON fájlba."""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"Hiba az adat mentésekor: {e}")
        return False

def to_local_format(item):
    if 'expiryDate' in item and item['expiryDate']:
        item['expiryDate'] = item['expiryDate']
    if 'createdAt' in item and item['createdAt']:
        item['createdAt'] = item['createdAt']
    return item

def generate_id():
    return str(int(time.time() * 1000))

def update_item_timestamps(item):
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
        
        # Létrehozzuk a globális JS változót (INGRESS_ENTRY_POINT végén van a perjel)
        js_injection = f'<script>window.HASS_API_BASE_PATH = "{INGRESS_ENTRY_POINT}";</script>'
        
        # Beillesztjük a </head> elé
        modified_html = html_content.replace('</head>', js_injection + '</head>')
        
        return modified_html
        
    except FileNotFoundError:
        return "Hiba: index.html fájl nem található.", 404

# 2. STATIKUS FÁJLOK KISZOLGÁLÁSA (JAVÍTVA)
# Ez kezeli a /.../ingress/style.css és a /.../ingress/app.js hívásokat
@app.route(f'{INGRESS_ENTRY_POINT}<path:filename>')
def serve_static(filename):
    """Statikus fájlok (JS, CSS, képek) kiszolgálása a www mappából az Ingress prefixet használva."""
    return send_from_directory('www', filename)

# 3. API VÉGPONTOK (INGRESS HELYESEN BEÉPÍTVE)

# GET route
# INGRESS_ENTRY_POINT + api/collection_name lesz az útvonal
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>', methods=['GET'])
def get_collection(collection_name):
    data = load_data()
    collection = data.get(collection_name, [])

    formatted_collection = []
    for item in collection:
        formatted_item = to_local_format(item)
        if collection_name == 'pantry':
             formatted_item['name'] = formatted_item['name'].lower().strip()
        
        formatted_collection.append(formatted_item)

    return jsonify(formatted_collection)

# POST route
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

# DELETE route
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>', methods=['DELETE'])
def delete_item(collection_name, item_id):
    data = load_data()
    collection = data.get(collection_name, [])

    initial_length = len(collection)
    data[collection_name] = [item for item in collection if item.get('id') != item_id]

    if len(data[collection_name]) < initial_length:
        if save_data(data):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Mentési hiba'}), 500
    else:
        return jsonify({'error': 'Elem nem található'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
