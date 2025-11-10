import json
import os
import time
import zipfile # ÚJ IMPORT
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory, send_file
from werkzeug.utils import secure_filename

# --- INGRESS BEÁLLÍTÁS ---
INGRESS_ENTRY_POINT = os.environ.get('SUPERVISOR_INGRESS_ENTRY', '/') 
if not INGRESS_ENTRY_POINT.endswith("/"):
    INGRESS_ENTRY_POINT += "/"

app = Flask(__name__)
DATA_FILE = "/data/app_data.json"

# A képek és a ZIP fájl célja is a perzisztens /data mappa
UPLOAD_FOLDER = "/data/images" 
TEMP_ZIP_PATH = "/data/mohakonyha_backup.zip" # ÚJ IDEIGLENES ZIP FÁJL

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# --- JSON fájlkezelő és Segédfüggvények (VÁLTOZATLAN) ---

def load_data():
    """Adatok betöltése a perzisztens JSON fájlból."""
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
    """Adatok mentése a perzisztens JSON fájlba."""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"[ERROR] Mentési hiba: {e}")
        return False

def to_local_format(item):
    return item

def generate_id():
    return str(int(time.time() * 1000))

def update_item_timestamps(item):
    now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    if 'createdAt' not in item:
        item['createdAt'] = now_iso
    return item

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- ÚTVONALAK ---

# 1. INDEX FÁJL KISZOLGÁLÁSA (VÁLTOZATLAN)
@app.route(INGRESS_ENTRY_POINT)
def serve_index():
    try:
        with open(os.path.join('www', 'index.html'), 'r', encoding='utf-8') as f:
            html_content = f.read()
        js_injection = f'<script>window.HASS_API_BASE_PATH = "{INGRESS_ENTRY_POINT}";</script>'
        modified_html = html_content.replace('</head>', js_injection + '</head>')
        return modified_html
    except FileNotFoundError:
        return "Hiba: index.html fájl nem található a 'www' mappában.", 404

# 2. STATIKUS FÁJLOK KISZOLGÁLÁSA (VÁLTOZATLAN)
@app.route(f'{INGRESS_ENTRY_POINT}<path:filename>')
def serve_static(filename):
    if filename.startswith('api/'):
         return "API végpont", 404
    return send_from_directory('www', filename)

# ÚJ VÉGPONT: Képek kiszolgálása a /data/images mappából (VÁLTOZATLAN)
@app.route(f'{INGRESS_ENTRY_POINT}api/images/<path:filename>')
def serve_image(filename):
    """Képek kiszolgálása a perzisztens /data/images mappából."""
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except FileNotFoundError:
        return jsonify({'error': 'Kép nem található'}), 404

# 3. API VÉGPONTOK (ADATOK - VÁLTOZATLAN)
@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>', methods=['GET'])
def get_collection(collection_name):
    # ... GET Logika ...
    data = load_data()
    collection = data.get(collection_name, [])
    formatted_collection = [to_local_format(item) for item in collection]
    return jsonify(formatted_collection)

@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>', methods=['POST'])
def add_item(collection_name):
    # ... POST Logika ...
    new_item = request.json
    new_item = update_item_timestamps(new_item)
    new_item['id'] = generate_id()
    data = load_data()
    data.get(collection_name, []).append(new_item)
    if save_data(data):
        return jsonify({'id': new_item['id'], 'success': True}), 201
    else:
        return jsonify({'error': 'Mentési hiba'}), 500

@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>', methods=['PUT'])
def update_item(collection_name, item_id):
    # ... PUT Logika ...
    updated_data = request.json
    data = load_data()
    collection = data.get(collection_name)
    if collection is None:
        return jsonify({'error': f'A gyűjtemény ({collection_name}) nem létezik'}), 400
    found = False
    for i, item in enumerate(collection):
        if item.get('id') == item_id:
            if 'createdAt' in updated_data:
                del updated_data['createdAt']
            collection[i].update(updated_data)
            collection[i]['id'] = item_id
            found = True
            break
    if found:
        if save_data(data):
            return jsonify({'success': True, 'id': item_id}), 200
        else:
            return jsonify({'error': 'Mentési hiba'}), 500
    else:
        return jsonify({'error': 'Elem nem található'}), 404

@app.route(f'{INGRESS_ENTRY_POINT}api/<collection_name>/<item_id>', methods=['DELETE'])
def delete_item(collection_name, item_id):
    # ... DELETE Logika ...
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

# BACKUP LETÖLTÉS (JELENTŐSEN MÓDOSÍTVA ZIP TÖMÖRÍTÉSSEL)
@app.route(f'{INGRESS_ENTRY_POINT}api/backup', methods=['GET'])
def download_backup():
    """Az app_data.json fájlt és a /data/images mappát ZIP-be tömöríti, majd letölti."""
    
    if not os.path.exists(DATA_FILE):
        return jsonify({'error': 'A mentési fájl nem található'}), 404

    try:
        # 1. ZIP fájl létrehozása
        with zipfile.ZipFile(TEMP_ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
            
            # 2. Hozzáadjuk az adatbázis JSON fájlt
            zipf.write(DATA_FILE, os.path.basename(DATA_FILE))
            
            # 3. Hozzáadjuk a képeket (ha létezik a mappa)
            if os.path.exists(UPLOAD_FOLDER):
                for folder_name, subfolders, filenames in os.walk(UPLOAD_FOLDER):
                    for filename in filenames:
                        file_path = os.path.join(folder_name, filename)
                        # A ZIP fájlban 'images/kepnev.png' néven tároljuk
                        zipf.write(file_path, os.path.join('images', filename))

        # 4. ZIP fájl elküldése
        response = send_file(TEMP_ZIP_PATH, 
                             as_attachment=True, 
                             mimetype='application/zip',
                             download_name='mohakonyha_full_backup.zip')

    except Exception as e:
        print(f"[ERROR] ZIP létrehozási/küldési hiba: {e}")
        return jsonify({'error': f'Hiba a backup tömörítésekor: {e}'}), 500

    finally:
        # 5. Ideiglenes ZIP fájl törlése
        if os.path.exists(TEMP_ZIP_PATH):
            os.remove(TEMP_ZIP_PATH)
            
    return response

# KÉPFELTÖLTÉS (VÁLTOZATLAN)
@app.route(f'{INGRESS_ENTRY_POINT}api/upload-image', methods=['POST'])
def upload_image():
    """Kép feltöltése a /data/images/ mappába."""
    if 'file' not in request.files:
        return jsonify({'error': 'Nincs fájl a kérésben'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nincs kiválasztott fájl'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        try:
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        except Exception as e:
            print(f"[ERROR] Nem sikerült létrehozni a mappát: {e}")
            return jsonify({'error': 'Mappa létrehozási hiba a szerveren'}), 500

        save_path = os.path.join(UPLOAD_FOLDER, filename)
        
        try:
            file.save(save_path) 
            return jsonify({'success': True, 'filename': filename}), 200
        except Exception as e:
            print(f"[ERROR] Fájlmentési hiba: {e}")
            return jsonify({'error': 'Fájlmentési hiba a szerveren'}), 500

    else:
        return jsonify({'error': 'Nem támogatott fájltípus'}), 400

# FUTTATÁS
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
