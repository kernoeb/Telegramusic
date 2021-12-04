FROM python:3.9

RUN apt update && apt install -y ffmpeg
RUN ffmpeg -version

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Temp fix
ARG COMMIT=d69983a8756fa75e16606bcd1b2ba50ec115ed16
RUN cd /tmp && wget https://github.com/ytdl-org/youtube-dl/archive/"${COMMIT}".zip && unzip "${COMMIT}.zip" && cd youtube-dl-"${COMMIT}" && pip install .

COPY . .

# Temp fix to avoid flac download
RUN mv ./fixes/deezer_settings.py /usr/local/lib/python3.9/site-packages/deezloader/deezloader/deezer_settings.py
RUN rm -rf ./fixes

CMD [ "python", "./main.py" ]