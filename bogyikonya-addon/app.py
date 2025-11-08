import json
import os
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
import urllib.request

app = Flask(__name__)
DATA_FILE = "/data/app_data.json"

# --- INGRESS ENTRY POINT ---
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
ADDON_SLUG = os.environ.get("HASSIO_ADDON") or "bogyikonya"

# Hardcode fallback URL (config.yaml vagy környezeti változó)
FALLBACK_INGRESS = os.environ.get("INGRESS_ENTRY") or "/hassio/addon/bogyikonya"

def get_ingress_url():
    """Lekérdezi az addon Ingress URL-jét a Supervisor API-n keresztül urllib-rel.
    Ha nincs token, vagy hiba van, fallback a hardcodeolt URL-re.
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
                return ingress_url
            else:
                print("[DEBUG] Supervisor API nem adott ingress_url-t, fallback hardcode URL")
                return FALLBACK_INGRESS
    except Exception as e:
        print(f"[DEBUG] Hiba az ingress_url lekérésekor: {e}, fallback hardcode URL")
        return FALLBACK_INGRESS

# Ingress path beállítása és végperjel biztosítása
INGRESS_ENTRY_POINT = get_ingress_url()
if not INGRESS_ENTRY_POINT.endswith("/"):
    INGRESS_ENTRY_POINT += "/"
print(f"[DEBUG] Ingress entry point: {INGRESS_ENTRY_POINT}")

# --- SEGÉDFÜGGVÉNYEK ---
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except Exception:
        data = {}
    default_data = {"preparedMeals": [], "pantry": [], "shoppingList": [], "recipes": []}
    for key in default_data:
        if key not in data:
            data[key] = default_data[key]
    return data

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[ERROR] Mentési hiba: {e}")
        return False

def generate_id():
    return str(int(time.time() * 1000))

def update_item_timestamps(item):
    now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    if 'createdAt' not in item:
        item['createdAt'] = now_iso
    return item

def to_local_format(item):
    if 'expiryDate' in item and item['expiryDate']:
        item['expiryDate'] = item['expiryDate']
    if 'createdAt' in item and item['createdAt']:
        item['createdAt'] = item['createdAt']
    return item

# --- ROUTEOK ---

# Index + JS injektálás
@app.route(f"{INGRESS_ENTRY_POINT}", defaults={"path": ""})
@app.route(f"{INGRESS_ENTRY_POINT}<path:path>")
def serve_index(path):
    try:
        with open(os.path.join('www', 'index.html'), 'r', encoding='utf-8') as f:
            html_content = f.read()
        js_injection = f'<script>window.HASS_API_BASE_PATH = "{INGRESS_ENTRY_POINT}";</script>'
        return html_content.replace('</head>', js_injection + '</head>')
    except FileNotFoundError:
        return "Hiba: index.html fájl nem található.", 404

# Statikus fájlok
@app.route(f"{INGRESS_ENTRY_POINT}<path:filename>")
def serve_static(filename):
    return send_from_directory('www', filename)

# GET + POST
@app.route(f"{INGRESS_ENTRY_POINT}api/<collection_name>", methods=['GET', 'POST'])
def handle_collection(collection_name):
    data = load_data()
    collection = data.get(collection_name, [])

    if request.method == 'GET':
        formatted = [to_local_format(item) for item in collection]
        return jsonify(formatted)

    elif request.method == 'POST':
        new_item = request.json
        new_item = update_item_timestamps(new_item)
        new_item['id'] = generate_id()
        collection.append(new_item)
        data[collection_name] = collection
        if save_data(data):
            return jsonify({'id': new_item['id'], 'success': True}), 201
        else:
            return jsonify({'error': 'Mentési hiba'}), 500

# DELETE
@app.route(f"{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>", methods=['DELETE'])
def delete_item(collection_name, item_id):
    data = load_data()
    collection = data.get(collection_name, [])
    initial_len = len(collection)
    data[collection_name] = [item for item in collection if item.get('id') != item_id]

    if len(data[collection_name]) < initial_len:
        if save_data(data):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Mentési hiba'}), 500
    else:
        return jsonify({'error': 'Elem nem található'}), 404

# --- FUTTATÁS ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
