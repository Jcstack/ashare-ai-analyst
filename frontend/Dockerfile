# Stage 1: Build the React SPA
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Copy dist to a volume-sharing image
# Store build output in /build/dist (NOT at the volume mount point)
# so the CMD can clean the volume and copy fresh files every restart
FROM alpine:3.19

COPY --from=build /app/dist /build/dist

CMD ["sh", "-c", "rm -rf /app/dist/* && cp -r /build/dist/. /app/dist/ && echo 'Frontend dist refreshed'"]
