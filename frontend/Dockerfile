# syntax=docker/dockerfile:1
# 多阶段构建：deps（依赖） -> dev（开发 bind mount） -> builder（next build） -> runner（standalone 运行）
# 开发 compose 使用 target: dev（源码 bind mount 热更新）；生产使用默认最后阶段 runner。

FROM node:22-alpine AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

# ---------- 阶段 1：安装依赖（层缓存：只在 lockfile 变化时失效） ----------
FROM base AS deps
RUN npm install -g pnpm@12.9.1
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# ---------- 阶段 2：开发镜像（compose 中 bind mount 源码，CMD pnpm dev） ----------
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

# ---------- 阶段 3：构建（next build，output: standalone） ----------
# 注意：Next.js 的 rewrites 在构建期序列化进产物，
# 因此后端地址需在构建时注入（compose: build.args BACKEND_INTERNAL_URL=http://backend:8000）
FROM deps AS builder
ARG BACKEND_INTERNAL_URL=http://localhost:8000
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL}
COPY . .
RUN pnpm build

# ---------- 阶段 4：生产运行（仅拷贝 standalone 产物，非 root 运行） ----------
FROM node:22-alpine AS runner
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
WORKDIR /app

RUN addgroup -S nodejs -g 1001 && adduser -S nextjs -u 1001 --ingroup nodejs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
