# Build from the repository root:
# docker build -f frontend/Dockerfile -t image-to-lego-frontend:local .
FROM node:22-alpine AS build

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# The renderer imports these checked-in conversion assets at build time.
COPY backend/app/conversion/part_geometry_assets /workspace/backend/app/conversion/part_geometry_assets
RUN npm run build

FROM nginx:1.27-alpine

COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

EXPOSE 8080
