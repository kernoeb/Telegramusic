FROM python:3.9-alpine3.15

RUN apk add --no-cache ffmpeg alpine-sdk python3-dev py3-setuptools tiff-dev jpeg-dev openjpeg-dev zlib-dev freetype-dev lcms2-dev \
    libwebp-dev tcl-dev tk-dev harfbuzz-dev fribidi-dev libimagequant-dev \
    libxcb-dev libpng-dev

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY patches/deezer_settings.py ./patches/deezer_settings.py
COPY langs.json ./
COPY main.py ./

# Temp fix to avoid flac download
RUN echo "Temp FLAC fix" && \
    mv ./patches/deezer_settings.py /usr/local/lib/python3.9/site-packages/deezloader/deezloader/deezer_settings.py \
    && rm -rf ./patches

CMD [ "python", "./main.py" ]