FROM node:20-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
COPY src/package.json ./src/package.json
RUN npm ci --workspace src --include-workspace-root=false
COPY src ./src
RUN npm run build --workspace src

FROM nginx:1.27-alpine
COPY src/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/src/dist /usr/share/nginx/html
