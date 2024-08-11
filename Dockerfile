FROM python:3.9.18-alpine3.19

RUN apk add --no-cache ffmpeg alpine-sdk python3-dev py3-setuptools tiff-dev jpeg-dev openjpeg-dev zlib-dev freetype-dev lcms2-dev \
    libwebp-dev tcl-dev tk-dev harfbuzz-dev fribidi-dev libimagequant-dev \
    libxcb-dev libpng-dev

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY patches/deezer_settings.py ./patches/deezer_settings.py
COPY handlers ./handlers
COPY langs.json ./
COPY main.py ./
COPY utils.py ./
COPY bot.py ./

# Avoid flac download, conditionally
ARG ENABLE_FLAC="0"
ENV ENABLE_FLAC=$ENABLE_FLAC

RUN echo "> ENABLE_FLAC : $ENABLE_FLAC"

RUN if [ "$ENABLE_FLAC" = "0" ]; then \
    echo "FLAC : disabled" && \
    mv ./patches/deezer_settings.py /usr/local/lib/python3.9/site-packages/deezloader/deezloader/deezer_settings.py && \
    rm -rf ./patches; \
    else \
    echo "FLAC : enabled" && \
    rm -rf ./patches; \
    fi

CMD [ "python", "./main.py" ]