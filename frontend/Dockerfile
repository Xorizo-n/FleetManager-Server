FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* .npmrc* ./
RUN npm install

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npx vite build

FROM nginx:1.27-alpine

# openssl — для временного самоподписанного сертификата (docker-entrypoint.d/40-fleet-tls.sh)
RUN apk add --no-cache openssl

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/api.conf /etc/nginx/fleet/api.conf
COPY docker-entrypoint.d/40-fleet-tls.sh /docker-entrypoint.d/40-fleet-tls.sh
RUN chmod +x /docker-entrypoint.d/40-fleet-tls.sh

# 443 — сайт по HTTPS, 80 — перенаправление на HTTPS, 8080 — API для агентов по HTTP
EXPOSE 80 443 8080

CMD ["nginx", "-g", "daemon off;"]
