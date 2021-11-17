FROM python:3.9

RUN apt update && apt install -y ffmpeg
RUN ffmpeg -version

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Temp fix
RUN cd /tmp && wget https://github.com/ytdl-org/youtube-dl/archive/8e069597c658810567ced5f8046dc5d14ab93037.zip && unzip 8e069597c658810567ced5f8046dc5d14ab93037.zip && cd youtube-dl-8e069597c658810567ced5f8046dc5d14ab93037 && pip install .

COPY . .

# Temp fix to avoid flac download
RUN mv ./fixes/deezer_settings.py /usr/local/lib/python3.9/site-packages/deezloader/deezloader/deezer_settings.py
RUN rm -rf ./fixes

CMD [ "python", "./main.py" ]