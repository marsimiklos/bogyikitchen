#!/usr/bin/env bash
# run.sh
# Ez a szkript elindítja a Python Flask szervert

echo "Bogyi Konyha add-on indul..."

# Ellenőrizzük, hogy létezik-e az adatfájl. Ha nem, létrehozzuk üres szerkezettel a perzisztens /data mappában.
DATA_FILE="/data/app_data.json"

if [ ! -f "$DATA_FILE" ]; then
    echo "Helyi adatfájl (${DATA_FILE}) létrehozása."
    cat > "$DATA_FILE" <<- EOL
{
    "preparedMeals": [],
    "pantry": [],
    "shoppingList": [],
    "recipes": []
}
EOL
fi

echo "Adatfájl ellenőrzés kész. Flask szerver indítása a 8099-es porton."

# A Flask alkalmazás futtatása.
python3 app.py
