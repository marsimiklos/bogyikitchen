import json
import os
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
import urllib.request

app = Flask(__name__)
DATA_FILE = "/data/app_data.json"

# --- INGRESS BEÁLLÍTÁS ---
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
ADDON_SLUG = os.environ.get("HASSIO_ADDON") or "bogyikonya"

# Hardcode fallback URL (beállítható config.yaml-ban vagy környezeti változóként)
FALLBACK_INGRESS = os.environ.get("INGRESS_ENTRY") or "/hassio/addon/bogyikonya/"

def get_ingress_url():
    """Lekérdezi az addon Ingress URL-jét a Supervisor API-n keresztül urllib-rel.
    Ha nincs token, fallback a hardcodeolt URL-re.
    """
    if not SUPERVISOR_TOKEN:
        print("[DEBUG] Supervisor token nincs beállítva, fallback hardcode URL")
        return FALLBACK_INGRESS

    url = f"http://supervisor/addons/{ADDON_SLUG}/info"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
            ingress_url = data.get("ingress_url")
            if ingress_url:
                return ingress_url if ingress_url.endswith("/") else ingress_url + "/"
            else:
                print("[DEBUG] Supervisor API nem adott ingress_url-t, fallback hardcode URL")
                return FALLBACK_INGRESS
    except Exception as e:
        print(f"[DEBUG] Hiba az ingress_url lekérésekor: {e}, fallback hardcode URL")
        return FALLBACK_INGRESS

# Beállítjuk a Flask app Ingress entry point-ját
INGRESS_ENTRY_POINT = get_ingress_url()
print(f"[DEBUG] Ingress entry point: {INGRESS_ENTRY_POINT}")

# --- JSON fájlkezelő és segédfüggvények ---
def load_data():
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
@app.route(INGRESS_ENTRY_POINT)
def serve_index():
    try:
        with open(os.path.join('www', 'index.html'), 'r', encoding='utf-8') as f:
            html_content = f.read()
        js_injection = f'<script>window.HASS_API_BASE_PATH = "{INGRESS_ENTRY_POINT}";</script>'
        modified_html = html_content.replace('</head>', js_injection + '</head>')
        return modified_html
    except FileNotFoundError:
        return "Hiba: index.html fájl nem található.", 404

@app.route(f'{INGRESS_ENTRY_POINT}<path:filename>')
def serve_static(filename):
    return send_from_directory('www', filename)

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
