# Les fichiers statiques, construits sous Node.js 16.
ARG NODE_VERSION=16
FROM node:${NODE_VERSION}-alpine AS assets
WORKDIR /src
COPY package.json ./
RUN npm install --ignore-scripts

# L'application, sous Python 3.8.
FROM python:3.8-slim
WORKDIR /app
COPY --from=assets /src/node_modules ./node_modules
COPY . .
RUN pip install --no-cache-dir .
CMD ["python", "-m", "app"]
