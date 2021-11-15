FROM python:3.9

RUN apt update && apt install -y ffmpeg
RUN ffmpeg -version

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Temp fix
RUN cd /tmp
RUN wget https://github.com/ytdl-org/youtube-dl/archive/8e069597c658810567ced5f8046dc5d14ab93037.zip
RUN unzip 8e069597c658810567ced5f8046dc5d14ab93037.zip
RUN cd youtube-dl-8e069597c658810567ced5f8046dc5d14ab93037
RUN pip install .

COPY . .

CMD [ "python", "./main.py" ]