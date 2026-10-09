FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate
WORKDIR /app

FROM base AS dependencies
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY patches ./patches
RUN pnpm install --frozen-lockfile

FROM base AS builder
ARG NEXT_PUBLIC_AKC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_AKC_DEMO_MODE=false
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV NEXT_PUBLIC_AKC_API_URL=$NEXT_PUBLIC_AKC_API_URL
ENV NEXT_PUBLIC_AKC_DEMO_MODE=$NEXT_PUBLIC_AKC_DEMO_MODE
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=dependencies /app/packages/contracts/node_modules ./packages/contracts/node_modules
COPY . .
RUN pnpm --filter @akc/web build

FROM debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a AS security-packages
# The pinned distroless release still carries deb13u2. Install genuine signed
# Debian security packages and preserve their package metadata in the final image.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libssl3t64=3.5.7-1~deb13u3 openssl-provider-legacy=3.5.7-1~deb13u3 \
    && mkdir -p /patched-root/var/lib/dpkg/status.d \
    && dpkg-query -L libssl3t64 openssl-provider-legacy | while IFS= read -r file; do \
        if [ -f "$file" ]; then cp --parents "$file" /patched-root/; fi; \
        done \
    && dpkg-query -s libssl3t64 > /patched-root/var/lib/dpkg/status.d/libssl3t64 \
    && dpkg-query -s openssl-provider-legacy > /patched-root/var/lib/dpkg/status.d/openssl-provider-legacy \
    && cp "$(dpkg-query --control-path libssl3t64 md5sums)" \
        /patched-root/var/lib/dpkg/status.d/libssl3t64.md5sums \
    && cp "$(dpkg-query --control-path openssl-provider-legacy md5sums)" \
        /patched-root/var/lib/dpkg/status.d/openssl-provider-legacy.md5sums \
    && rm -rf /var/lib/apt/lists/*

FROM gcr.io/distroless/nodejs24-debian13:nonroot@sha256:bb6b03d81066993293a10feda7250e8e1cc034035fe9b61cfceededa7c8bf04d AS runtime
COPY --from=security-packages /patched-root/ /
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=builder --chown=nonroot:nonroot /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nonroot:nonroot /app/apps/web/.next/static ./apps/web/.next/static
USER nonroot
EXPOSE 3000
CMD ["apps/web/server.js"]
