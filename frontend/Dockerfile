FROM node:24.22.1-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY tsconfig*.json vite.config.ts eslint.config.js index.html ./
COPY src ./src
COPY public ./public

# Keep the demo available until the payments API is implemented.
ARG VITE_API_MODE=mock
ENV VITE_API_MODE=$VITE_API_MODE VITE_API_BASE_URL=/api/v1
RUN test "$VITE_API_MODE" = mock || test "$VITE_API_MODE" = real
RUN npm run typecheck && npm run lint && npm run build

FROM nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951
COPY nginx.conf /etc/nginx/nginx.conf
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
