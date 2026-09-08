FROM node:24-alpine AS build
ARG VOICE_NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --registry "$VOICE_NPM_REGISTRY"
COPY . .
RUN npm run build
FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
