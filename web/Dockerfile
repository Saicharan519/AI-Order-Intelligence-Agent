# The web app as a small production image: Next.js "standalone" output (server.js plus only
# the files it needs), run as the unprivileged node user. Built from web/:
#   docker compose --profile app build web
# It talks to the API at API_URL on Docker's private network and is reached only through Caddy.

FROM node:24.11-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24.11-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# public/ is empty and git keeps no empty folders, so a fresh clone has none: create it.
RUN mkdir -p public && npm run build

FROM node:24.11-bookworm-slim AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
