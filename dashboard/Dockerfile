# Dashboard Dockerfile
# Multi-stage build for React/Vite app

# Build stage
FROM node:20-alpine as builder

ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]