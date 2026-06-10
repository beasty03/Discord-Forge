FROM python:3.12-slim

WORKDIR /bot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# BOT_CONFIG_JSON is injected at container start by bot_docker.py
# BOT_NAME selects which bot from the config to run
ENV BOT_NAME=""
ENV BOT_CONFIG_JSON=""
ENV FORGE_API_URL="http://discordforge:5000"

CMD ["python", "launcher.py"]
