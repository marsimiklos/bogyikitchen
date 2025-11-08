ARG BUILD_FROM
FROM $BUILD_FROM

# Telepítjük a Python-t és a pip-et
RUN apk add --no-cache python3 py3-pip

# Telepítjük a Flask Python web keretrendszert
# A --break-system-packages paraméter fixeli a "externally-managed-environment" hibát
RUN pip3 install Flask --break-system-packages

# Létrehozzuk a munka könyvtárat
WORKDIR /app

# Másoljuk az alkalmazás fájljait
COPY app.py .
COPY www /app/www

# Adunk futási engedélyt a start szkriptnek
COPY run.sh .
RUN chmod a+x /app/run.sh

# A run.sh lesz a belépési pont.
CMD [ "/./run.sh" ]
